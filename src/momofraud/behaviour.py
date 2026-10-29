"""Behavioural features, computed point-in-time.

Every feature for a transaction uses only what the operator knew *before* that
transaction: the transaction itself, the history of the accounts involved, and
account events such as SIM swaps. FeatureState replays history in time order and,
for each transaction, computes the features first and only then updates its memory.

The same class serves both purposes:
- offline, `compute_features()` replays a whole simulated world to build training data;
- online (stages 4-5), the API keeps one FeatureState and scores each new transaction
  as it arrives.
So there is no separate "training" and "serving" feature code that could drift apart.

Feature groups (also used for the ablation study in reports/behaviour.md):

transaction  what is in the transaction itself (as in stages 1-2)
sender       how this sender usually behaves: history length, typical amounts, recent activity
device       is this phone new for this account, and was there a recent SIM swap or PIN reset
recipient    has the sender paid this account before
receiver     what the receiving account looks like: age, money coming in from strangers,
             how quickly it withdraws what it receives (mule-like behaviour)
agent        for withdrawals: is this a new agent for the customer, in another town, and is
             the agent sending many requests that get declined
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HOUR, DAY = 3600, 86_400
CAP_HOURS = 24 * 30.0          # "never" / "long ago" is capped at 30 days
EWM_ALPHA = 0.1                # weight of the newest amount in the running average
SECURITY_EVENTS = ("SIM_SWAP", "PIN_RESET")

FEATURE_GROUPS: dict[str, list[str]] = {
    "transaction": [
        "is_transfer", "is_agent_request", "log_amount", "log_sender_balance_before",
        "amount_to_balance", "empties_account", "log_receiver_balance_before", "receiver_untracked",
        "amount_is_round", "hour",
    ],
    "sender": [
        "sender_history", "sender_age_days", "hours_since_sender_last_tx", "amount_zscore",
        "sender_out_count_24h", "log_sender_out_amount_24h",
    ],
    "device": [
        "device_new", "device_history", "hours_since_device_first_seen",
        "hours_since_sim_swap_or_pin_reset", "hours_since_device_change",
    ],
    "recipient": ["recipient_new", "pair_history"],
    "receiver": [
        "receiver_age_days", "receiver_history", "receiver_in_count_24h", "receiver_distinct_senders_7d",
        "receiver_stranger_share_7d", "receiver_cashout_ratio_7d",
    ],
    "agent": [
        "agent_new_for_sender", "region_mismatch", "agent_requests_1h", "agent_decline_rate_24h",
    ],
}
FEATURES = [f for group in FEATURE_GROUPS.values() for f in group]


@dataclass
class Transaction:
    """The fields the feature engine needs, as plain Python values."""

    t: int                  # seconds since the simulation start
    type: str
    channel: str
    status: str
    amount: float
    sender: str
    receiver: str
    sender_balance_before: float     # nan when the account's balance is not tracked
    receiver_balance_before: float
    device: str | None


@dataclass
class FeatureState:
    """Running memory of the network. Feed it transactions and account events in time order."""

    opened_t: dict[str, int] = field(default_factory=dict)     # account -> opening time (s)
    region: dict[str, str] = field(default_factory=dict)
    sender_count: defaultdict = field(default_factory=lambda: defaultdict(int))
    activity: defaultdict = field(default_factory=lambda: defaultdict(int))
    last_tx_t: dict = field(default_factory=dict)
    amount_mean: dict = field(default_factory=dict)            # running (EWM) mean of log amount
    amount_var: dict = field(default_factory=dict)
    amount_n: defaultdict = field(default_factory=lambda: defaultdict(int))
    out_24h: defaultdict = field(default_factory=lambda: defaultdict(deque))      # (t, amount)
    device_count: defaultdict = field(default_factory=lambda: defaultdict(int))  # (account, device)
    device_first_t: dict = field(default_factory=dict)                           # (account, device)
    pair_count: defaultdict = field(default_factory=lambda: defaultdict(int))    # (sender, receiver)
    last_security_t: dict = field(default_factory=dict)
    last_device_change_t: dict = field(default_factory=dict)
    in_7d: defaultdict = field(default_factory=lambda: defaultdict(deque))  # (t, sender, amount, stranger)
    cashout_7d: defaultdict = field(default_factory=lambda: defaultdict(deque))  # (t, amount)
    agent_requests_24h: defaultdict = field(default_factory=lambda: defaultdict(deque))  # (t, declined)

    @classmethod
    def from_accounts(cls, accounts: pd.DataFrame, start: pd.Timestamp) -> FeatureState:
        opened = ((accounts["opened"] - start).dt.total_seconds()).astype("int64")
        return cls(opened_t=dict(zip(accounts["account"], opened, strict=True)),
                   region=dict(zip(accounts["account"], accounts["region"], strict=True)))

    # -- account events --------------------------------------------------------------------
    def observe_event(self, t: int, account: str, event: str) -> None:
        if event in SECURITY_EVENTS:
            self.last_security_t[account] = t
        elif event == "DEVICE_CHANGE":
            self.last_device_change_t[account] = t

    # -- features --------------------------------------------------------------------------
    def features(self, tx: Transaction) -> list[float]:
        """Features for tx using only the past. Call before observe(tx)."""
        t, s, r, amount = tx.t, tx.sender, tx.receiver, tx.amount
        before, r_before = tx.sender_balance_before, tx.receiver_balance_before
        is_cash_out = tx.type == "CASH_OUT"

        # transaction
        log_before = math.log1p(before) if before == before else 0.0
        transaction = [
            float(tx.type == "TRANSFER"), float(tx.channel == "AGENT_REQUEST"), math.log1p(amount),
            log_before, min(amount / max(before, 1.0), 10.0) if before == before else 0.0,
            float(before == before and amount * 1.002 >= before * 0.99),
            math.log1p(r_before) if r_before == r_before else 0.0, float(r_before != r_before),
            float(amount % 1000 == 0), float((t // HOUR) % 24),
        ]

        # sender
        n = self.amount_n[s]
        if n >= 3:
            sd = math.sqrt(self.amount_var[s]) + 0.25
            zscore = (math.log1p(amount) - self.amount_mean[s]) / sd
        else:
            zscore = 0.0
        out = _prune(self.out_24h[s], t - DAY)
        sender = [
            math.log1p(self.sender_count[s]), _age_days(self.opened_t, s, t),
            _hours_since(self.last_tx_t.get(s), t), zscore,
            float(len(out)), math.log1p(sum(a for _, a in out)),
        ]

        # device
        device_seen = self.device_count[(s, tx.device)] if tx.device else 1
        # A phone "warmed up" with a purchase an hour ago is not new, but it is still young
        first_seen = self.device_first_t.get((s, tx.device)) if tx.device else None
        device = [
            float(device_seen == 0), math.log1p(device_seen),
            0.0 if tx.device and first_seen is None else _hours_since(first_seen, t),
            _hours_since(self.last_security_t.get(s), t), _hours_since(self.last_device_change_t.get(s), t),
        ]

        # recipient
        pair = self.pair_count[(s, r)]
        recipient = [float(pair == 0), math.log1p(pair)]

        # receiver (mule-like signals; zero for agents, whose balances aren't tracked)
        incoming = _prune(self.in_7d[r], t - 7 * DAY)
        received = sum(a for _, _, a, _ in incoming)
        cashed = sum(a for _, a in _prune(self.cashout_7d[r], t - 7 * DAY))
        receiver = [
            _age_days(self.opened_t, r, t), math.log1p(self.activity[r]),
            float(sum(1 for tt, *_ in incoming if tt >= t - DAY)),
            float(len({snd for _, snd, _, _ in incoming})),
            (sum(st for *_, st in incoming) / len(incoming)) if incoming else 0.0,
            min(cashed / received, 2.0) if received else 0.0,
        ]

        # agent (withdrawals) / region
        if is_cash_out:
            requests = _prune(self.agent_requests_24h[r], t - DAY)
            n_req = len(requests)
            agent = [
                float(pair == 0), float(self.region.get(s) != self.region.get(r)),
                float(sum(1 for tt, _ in requests if tt >= t - HOUR)),
                sum(d for _, d in requests) / (n_req + 5),  # smoothed so one decline isn't 100%
            ]
        else:
            agent = [0.0, float(self.region.get(s) != self.region.get(r)), 0.0, 0.0]

        return transaction + sender + device + recipient + receiver + agent

    # -- memory update -----------------------------------------------------------------------
    def observe(self, tx: Transaction) -> None:
        """Add a transaction (of any type and status) to the network's memory."""
        t, s, r, amount = tx.t, tx.sender, tx.receiver, tx.amount
        ok = tx.status == "SUCCESS"
        self.sender_count[s] += 1
        self.activity[s] += 1
        self.activity[r] += 1
        self.last_tx_t[s] = t
        if tx.device:
            self.device_count[(s, tx.device)] += 1
            self.device_first_t.setdefault((s, tx.device), t)
        if tx.type == "CASH_OUT" and tx.channel == "AGENT_REQUEST":
            self.agent_requests_24h[r].append((t, float(tx.status == "DECLINED")))
        if not ok:
            return
        if tx.type in ("TRANSFER", "CASH_OUT", "PAYMENT", "BILL"):
            x = math.log1p(amount)
            if self.amount_n[s] == 0:
                self.amount_mean[s], self.amount_var[s] = x, 0.0
            else:
                delta = x - self.amount_mean[s]
                self.amount_mean[s] += EWM_ALPHA * delta
                self.amount_var[s] = (1 - EWM_ALPHA) * (self.amount_var[s] + EWM_ALPHA * delta * delta)
            self.amount_n[s] += 1
            self.out_24h[s].append((t, amount))
        if tx.type == "TRANSFER":
            stranger = float(self.pair_count[(s, r)] == 0 and self.pair_count[(r, s)] == 0)
            self.in_7d[r].append((t, s, amount, stranger))
        if tx.type == "CASH_OUT":
            self.cashout_7d[s].append((t, amount))
        self.pair_count[(s, r)] += 1


def _prune(window: deque, oldest: int) -> deque:
    while window and window[0][0] < oldest:
        window.popleft()
    return window


def _hours_since(then: int | None, now: int) -> float:
    return CAP_HOURS if then is None else min((now - then) / HOUR, CAP_HOURS)


def _age_days(opened: dict, account: str, now: int) -> float:
    return max((now - opened[account]) / DAY, 0.0) if account in opened else 0.0


SCORED_TYPES = ("TRANSFER", "CASH_OUT")


def compute_features(world: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Replay a simulated world and return features for every transfer and withdrawal.

    Returns one row per scored transaction, indexed by tx_id, with the FEATURES columns.
    """
    tx, events = world["transactions"], world["account_events"]
    start = tx["timestamp"].min().normalize()
    state = FeatureState.from_accounts(world["accounts"], start)

    t_tx = ((tx["timestamp"] - start).dt.total_seconds()).astype("int64").to_numpy()
    t_ev = ((events["timestamp"] - start).dt.total_seconds()).astype("int64").to_numpy()
    ev_account, ev_kind = events["account"].astype(str).tolist(), events["event"].astype(str).tolist()

    columns = [tx[c].astype(object).where(tx[c].notna(), None).tolist() if c == "device"
               else tx[c].astype(str).tolist() if c in ("type", "channel", "status", "sender", "receiver")
               else tx[c].to_numpy().tolist()
               for c in ("type", "channel", "status", "amount", "sender", "receiver",
                         "sender_balance_before", "receiver_balance_before", "device")]
    tx_ids = tx["tx_id"].to_numpy()

    rows, ids = [], []
    e = 0
    for i, (type_, channel, status, amount, sender, receiver, s_before, r_before, device) in enumerate(
            zip(*columns, strict=True)):
        t = int(t_tx[i])
        while e < len(t_ev) and t_ev[e] <= t:
            state.observe_event(int(t_ev[e]), ev_account[e], ev_kind[e])
            e += 1
        record = Transaction(t, type_, channel, status, amount, sender, receiver, s_before, r_before, device)
        if type_ in SCORED_TYPES:
            rows.append(state.features(record))
            ids.append(tx_ids[i])
        state.observe(record)

    return pd.DataFrame(np.asarray(rows, dtype=np.float32), columns=FEATURES,
                        index=pd.Index(ids, name="tx_id"))
