"""The live state the API scores against: accounts, balances, history and the clock.

At start-up the network replays a small simulated world (by default 3,000 people over
30 days) so every account already has a realistic history. After that, each new
transaction is scored against the current state and then, if committed, applied:
balances change and the FeatureState remembers it, exactly as in training.

One process owns this state. Scaling out to several API workers would need the state
in a shared store (Redis, for example); that is out of scope here and noted in the docs.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import pandas as pd

from momofraud.behaviour import FeatureState, Transaction
from momofraud.sim.config import TRANSFER_TAX, FraudConfig, SimConfig
from momofraud.sim.engine import simulate

PUBLIC_KIND = {"customer": "customer", "mule": "customer", "scammer": "customer",
               "agent": "agent", "merchant": "merchant", "external": "external"}
TRACKED_KINDS = {"customer"}
TAXED = {"TRANSFER", "CASH_OUT"}


class NetworkError(ValueError):
    """A request the network cannot apply (unknown account, time going backwards...)."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class Network:
    start: pd.Timestamp
    state: FeatureState
    kind: dict[str, str]                 # public kind: customer / agent / merchant / external
    region: dict[str, str]
    balance: dict[str, float]            # tracked (customer) accounts only
    device: dict[str, str] = field(default_factory=dict)    # last device seen per account
    recent: defaultdict = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=20)))
    now: int = 0                         # seconds since start
    next_id: int = 0

    # -- construction --------------------------------------------------------------------------
    @classmethod
    def from_world(cls, world: dict[str, pd.DataFrame]) -> Network:
        tx, events, accounts = world["transactions"], world["account_events"], world["accounts"]
        start = tx["timestamp"].min().normalize()
        net = cls(
            start=start,
            state=FeatureState.from_accounts(accounts, start),
            kind={a: PUBLIC_KIND[str(k)]
                  for a, k in zip(accounts["account"], accounts["kind"], strict=True)},
            region=dict(zip(accounts["account"], accounts["region"], strict=True)),
            balance={},
        )
        t_tx = ((tx["timestamp"] - start).dt.total_seconds()).astype("int64").tolist()
        t_ev = ((events["timestamp"] - start).dt.total_seconds()).astype("int64").tolist()
        ev = list(zip(t_ev, events["account"].astype(str), events["event"].astype(str), strict=True))
        cols = [tx[c].astype(str).tolist() for c in ("type", "channel", "status", "sender", "receiver")]
        nums = [tx[c].tolist() for c in ("amount", "sender_balance_before", "receiver_balance_before",
                                          "sender_balance_after", "receiver_balance_after")]
        devices = tx["device"].astype(object).where(tx["device"].notna(), None).tolist()
        e = 0
        for i, t in enumerate(t_tx):
            while e < len(ev) and ev[e][0] <= t:
                net.state.observe_event(*ev[e])
                e += 1
            type_, channel, status, sender, receiver = (c[i] for c in cols)
            amount, s_before, r_before, s_after, r_after = (c[i] for c in nums)
            record = Transaction(t, type_, channel, status, amount, sender, receiver, s_before, r_before,
                                 devices[i])
            net.state.observe(record)
            if s_after == s_after:
                net.balance[sender] = s_after
            if r_after == r_after:
                net.balance[receiver] = r_after
            if devices[i]:
                net.device[sender] = devices[i]
            entry = {"tx_id": i, "timestamp": net.timestamp(t), "type": type_, "amount": amount,
                     "sender": sender, "receiver": receiver, "status": status}
            net.recent[sender].append(entry)
            net.recent[receiver].append(entry)
        for t, account, event in ev[e:]:
            net.state.observe_event(t, account, event)
        for account, k in net.kind.items():
            if k == "customer":
                net.balance.setdefault(account, 0.0)
        net.now = max(t_tx[-1] if t_tx else 0, t_ev[-1] if t_ev else 0)
        net.next_id = len(t_tx) - 1
        return net

    @classmethod
    def demo(cls, users: int = 3000, days: int = 30, seed: int = 7) -> Network:
        cfg = SimConfig(n_users=users, days=days, seed=seed, fraud=FraudConfig(adaptive_share=0.5))
        return cls.from_world(simulate(cfg))

    # -- time ----------------------------------------------------------------------------------
    def to_seconds(self, timestamp: pd.Timestamp | None) -> int:
        if timestamp is None:
            return self.now + 1
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("Africa/Douala").tz_localize(None)
        t = int((ts - self.start).total_seconds())
        if t < self.now:
            current = self.timestamp(self.now)
            raise NetworkError(f"timestamp is before the network's current time ({current}): "
                               "transactions must arrive in time order", status=409)
        return t

    def timestamp(self, t: int) -> str:
        return (self.start + pd.Timedelta(seconds=t)).isoformat()

    # -- accounts ------------------------------------------------------------------------------
    def require(self, account: str, role: str) -> None:
        if account not in self.kind:
            raise NetworkError(f"unknown {role} account: {account}", status=404)

    def open_account(self, account: str, kind: str, region: str, t: int) -> None:
        if account in self.kind:
            raise NetworkError(f"account {account} already exists", status=409)
        self.kind[account] = kind
        self.region[account] = region
        self.state.opened_t[account] = t
        self.state.region[account] = region
        if kind in TRACKED_KINDS:
            self.balance[account] = 0.0
        self.now = max(self.now, t)

    def account_event(self, account: str, event: str, device: str | None, t: int) -> None:
        self.require(account, "event")
        self.state.observe_event(t, account, event)
        if device:
            self.device[account] = device
        self.now = max(self.now, t)

    # -- transactions --------------------------------------------------------------------------
    def build(self, type_: str, channel: str, sender: str, receiver: str, amount: float,
              device: str | None, t: int) -> Transaction:
        self.require(sender, "sender")
        self.require(receiver, "receiver")
        if sender == receiver:
            raise NetworkError("sender and receiver must be different accounts")
        s_before = self.balance.get(sender, math.nan)
        r_before = self.balance.get(receiver, math.nan)
        return Transaction(t, type_, channel, "SUCCESS", float(amount), sender, receiver, s_before, r_before,
                           device)

    def fee(self, record: Transaction) -> float:
        return math.ceil(record.amount * TRANSFER_TAX) if record.type in TAXED else 0.0

    def apply(self, record: Transaction, status: str) -> str:
        """Commit a transaction with the given outcome; returns the final status."""
        fee = self.fee(record)
        tracked_sender = record.sender in self.balance
        if status == "SUCCESS" and tracked_sender and self.balance[record.sender] < record.amount + fee:
            status = "FAILED_FUNDS"
        record.status = status
        self.state.observe(record)
        if status == "SUCCESS":
            if tracked_sender:
                self.balance[record.sender] -= record.amount + fee
            if record.receiver in self.balance:
                self.balance[record.receiver] += record.amount
        if record.device:
            self.device[record.sender] = record.device
        self.next_id += 1
        entry = {"tx_id": self.next_id, "timestamp": self.timestamp(record.t), "type": record.type,
                 "amount": record.amount, "sender": record.sender, "receiver": record.receiver,
                 "status": status}
        self.recent[record.sender].append(entry)
        self.recent[record.receiver].append(entry)
        self.now = max(self.now, record.t)
        return status
