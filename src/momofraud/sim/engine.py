"""Executes the simulation in time order, keeping every balance consistent.

Legitimate activity is planned up front (legit.py). Anything that depends on the state
at the time it happens (fraudsters reading the victim's balance, mules cashing out
what they received, people withdrawing money they were just sent) is scheduled on a
priority queue while the simulation runs.
"""

from __future__ import annotations

import heapq
import math
from array import array
from dataclasses import dataclass, field
from itertools import count

import numpy as np
import pandas as pd

from momofraud.sim import fraud
from momofraud.sim.config import TRANSFER_TAX, SimConfig
from momofraud.sim.legit import CHANNELS, SECONDS_PER_DAY, TYPES, C, T, plan_legit
from momofraud.sim.population import KINDS, Population, build_population

TAXED = {T["TRANSFER"], T["CASH_OUT"]}
FLEXIBLE = {T["TRANSFER"], T["CASH_OUT"]}  # amounts people adjust to what they have
STATUSES = ("SUCCESS", "FAILED_FUNDS", "DECLINED")
REACTIVE_MIN_AMOUNT = 10_000


@dataclass(frozen=True)
class Label:
    scenario: str = ""
    role: str = ""          # victim_debit | mule_cashout | attempt | warmup
    strategy: str = ""      # naive | adaptive
    attack_id: int = -1

    @property
    def is_fraud(self) -> int:
        return int(bool(self.scenario))


LEGIT = Label()


@dataclass
class Simulation:
    cfg: SimConfig
    rng: np.random.Generator
    pop: Population
    balance: list[float]
    device: list[int]
    blocked_until: list[int]
    queue: list = field(default_factory=list)
    rows: dict[str, array] = field(default_factory=lambda: {k: array(code) for k, code in ROW_TYPES.items()})
    account_events: list[tuple] = field(default_factory=list)
    takeover_targets: dict[int, float] = field(default_factory=dict)
    _seq: count = field(default_factory=count)
    _next_device: count = field(default_factory=lambda: count(1))
    _next_attack: count = field(default_factory=count)

    # -- scheduling -------------------------------------------------------------------
    def schedule(self, t: float, handler, *args) -> None:
        if t < self.cfg.days * SECONDS_PER_DAY:
            heapq.heappush(self.queue, (int(t), next(self._seq), handler, args))

    def new_device(self) -> int:
        return next(self._next_device)

    def new_attack_id(self) -> int:
        return next(self._next_attack)

    def record_account_event(self, t: int, account: int, event: str, device: int) -> None:
        self.account_events.append((t, account, event, device))

    # -- money movement ---------------------------------------------------------------
    def transact(self, t: int, type_: int, channel: int, sender: int, receiver: int, amount: float,
                 device: int | None = None, label: Label = LEGIT, declined: bool = False,
                 retry: bool = False) -> bool:
        """Move money if the sender can afford it; always record the attempt."""
        if sender == receiver:
            raise ValueError(f"self-transfer for account {sender}")
        tracked = self.pop.tracked
        if (not label.scenario and not retry and type_ in FLEXIBLE and tracked[sender]
                and amount * (1 + TRANSFER_TAX) > self.balance[sender]
                and self.rng.random() < self.cfg.adjust_to_balance):
            # People usually know roughly what they have: they send what they can instead
            amount = math.floor(self.balance[sender] * self.rng.uniform(0.6, 0.95) / 500) * 500
            if amount < 500:
                return False  # not worth it: they don't try at all
        elif (not label.scenario and not retry and type_ not in FLEXIBLE and tracked[sender]
              and type_ != T["CASH_IN"] and amount > self.balance[sender]
              and self.rng.random() < self.cfg.top_up_before_paying):
            # Fixed amounts (a bill, a purchase): people short of money deposit cash first
            shortfall = amount - self.balance[sender]
            deposit = math.ceil(shortfall / 1000) * 1000 + float(self.rng.choice([0, 1000, 2000, 5000]))
            agents = self.pop.home_agents[sender]
            # Recorded at the same second as the payment: every row's balance must follow
            # on from the previous row for that account, so nothing is back-dated
            self.transact(t, T["CASH_IN"], C["AGENT"], int(agents[self.rng.integers(len(agents))]),
                          sender, deposit)
        amount = float(round(amount, 2))
        fee = math.ceil(amount * TRANSFER_TAX) if type_ in TAXED else 0
        s_before = self.balance[sender] if tracked[sender] else math.nan
        r_before = self.balance[receiver] if tracked[receiver] else math.nan
        if device is None and tracked[sender]:
            device = self.device[sender]

        if declined:
            status = 2
        elif tracked[sender] and s_before < amount + fee:
            status = 1
        else:
            status = 0
            if tracked[sender]:
                self.balance[sender] = s_before - amount - fee
            if tracked[receiver]:
                self.balance[receiver] = r_before + amount

        r = self.rows
        r["t"].append(t)
        r["type"].append(type_)
        r["channel"].append(channel)
        r["status"].append(status)
        r["amount"].append(amount)
        r["fee"].append(fee if status == 0 else 0)
        r["sender"].append(sender)
        r["receiver"].append(receiver)
        r["sender_balance_before"].append(s_before)
        r["sender_balance_after"].append(self.balance[sender] if tracked[sender] else math.nan)
        r["receiver_balance_before"].append(r_before)
        r["receiver_balance_after"].append(self.balance[receiver] if tracked[receiver] else math.nan)
        r["device"].append(device if device is not None else -1)
        r["scenario"].append(SCENARIOS.index(label.scenario))
        r["role"].append(ROLES.index(label.role))
        r["strategy"].append(STRATEGIES.index(label.strategy))
        r["attack_id"].append(label.attack_id)

        if status == 0 and not label.scenario:
            self._maybe_react(t, type_, receiver, amount)
        if status == 1 and not label.scenario and not retry:
            self._maybe_top_up(t, type_, channel, sender, receiver, amount + fee - s_before)
        if status == 0 and label.scenario:
            fraud.on_fraud_credit(self, t, receiver, amount, label)
        return status == 0

    def _maybe_react(self, t: int, type_: int, receiver: int, amount: float) -> None:
        """Some people withdraw money soon after receiving it: legitimate behaviour that
        looks like a mule's, so a model can't just learn "receive then cash out = fraud"."""
        if type_ not in (T["TRANSFER"], T["SALARY"]) or amount < REACTIVE_MIN_AMOUNT:
            return
        if self.pop.kind[receiver] not in (KINDS.index("customer"), KINDS.index("mule")):
            return
        if self.rng.random() >= self.cfg.cash_out_after_receipt:
            return
        share = self.rng.uniform(0.5, 1.0)
        delay = self.rng.uniform(10 * 60, 6 * 3600)
        self.schedule(t + delay, _legit_cash_out, receiver, max(500.0, round(amount * share / 500) * 500))

    def _maybe_top_up(self, t: int, type_: int, channel: int, sender: int, receiver: int,
                      shortfall: float) -> None:
        """Short of money, people often deposit cash at an agent and try again."""
        if self.rng.random() >= self.cfg.top_up_after_failure:
            return
        deposit = math.ceil(shortfall / 1000) * 1000 + float(self.rng.choice([0, 1000, 2000, 5000]))
        when = t + self.rng.uniform(5 * 60, 40 * 60)
        self.schedule(when, _top_up_and_retry, sender, deposit, type_, channel, receiver, float(
            self.rows["amount"][-1]))

    # -- main loop --------------------------------------------------------------------
    def run(self, plan: pd.DataFrame, chunk: int = 250_000) -> None:
        columns = ("t", "type", "channel", "sender", "receiver", "amount", "declined")
        for start in range(0, len(plan), chunk):
            part = plan.iloc[start:start + chunk]
            for t, type_, channel, sender, receiver, amount, declined in zip(
                *(part[c].to_numpy().tolist() for c in columns), strict=True
            ):
                while self.queue and self.queue[0][0] <= t:
                    qt, _, handler, args = heapq.heappop(self.queue)
                    handler(self, qt, *args)
                if self.blocked_until[sender] > t:
                    continue  # the owner's SIM was swapped: they can't transact until it is restored
                self.transact(t, type_, channel, sender, receiver, amount, declined=declined)
        while self.queue:
            qt, _, handler, args = heapq.heappop(self.queue)
            handler(self, qt, *args)

# Compact typed columns: a 90-day run has ~5 million rows
ROW_TYPES = {
    "t": "q", "type": "b", "channel": "b", "status": "b", "amount": "d", "fee": "d",
    "sender": "i", "receiver": "i", "sender_balance_before": "d", "sender_balance_after": "d",
    "receiver_balance_before": "d", "receiver_balance_after": "d", "device": "i",
    "scenario": "b", "role": "b", "strategy": "b", "attack_id": "i",
}
SCENARIOS = ("", "account_takeover", "withdrawal_request", "wrong_transfer")
ROLES = ("", "victim_debit", "mule_cashout", "attempt", "warmup")
STRATEGIES = ("", "naive", "adaptive", "rented")


def _legit_cash_out(sim: Simulation, t: int, person: int, amount: float) -> None:
    agents = sim.pop.home_agents[person]
    agent = agents[sim.rng.integers(len(agents))]
    channel = C["AGENT_REQUEST"] if sim.rng.random() < 0.6 else C["USSD"]
    sim.transact(t, T["CASH_OUT"], channel, person, int(agent), amount)


def _top_up_and_retry(sim: Simulation, t: int, person: int, deposit: float, type_: int, channel: int,
                      receiver: int, amount: float) -> None:
    agents = sim.pop.home_agents[person]
    sim.transact(t, T["CASH_IN"], C["AGENT"], int(agents[sim.rng.integers(len(agents))]), person, deposit)
    sim.schedule(t + sim.rng.uniform(60, 300), _retry, type_, channel, person, receiver, amount)


def _retry(sim: Simulation, t: int, type_: int, channel: int, person: int, receiver: int,
           amount: float) -> None:
    sim.transact(t, type_, channel, person, receiver, amount, retry=True)


def _legit_pin_reset(sim: Simulation, t: int, person: int) -> None:
    sim.record_account_event(t, person, "PIN_RESET", sim.device[person])


def _legit_sim_replacement(sim: Simulation, t: int, person: int) -> None:
    """A lost or broken phone: a new SIM in a new phone, for the real owner."""
    sim.device[person] = sim.new_device()
    sim.record_account_event(t, person, "SIM_SWAP", sim.device[person])


def _legit_device_change(sim: Simulation, t: int, person: int) -> None:
    sim.device[person] = sim.new_device()
    sim.record_account_event(t, person, "DEVICE_CHANGE", sim.device[person])


def simulate(cfg: SimConfig | None = None) -> dict[str, pd.DataFrame]:
    """Run a full simulation and return transactions, account events and accounts."""
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    pop = build_population(cfg, rng)
    plan = plan_legit(pop, cfg, rng)

    n = len(pop.names)
    sim = Simulation(
        cfg=cfg, rng=rng, pop=pop, balance=pop.initial_balance.tolist(),
        device=[0] * n, blocked_until=[0] * n,
    )
    sim.device = [sim.new_device() if pop.tracked[i] else -1 for i in range(n)]

    # Legitimate phone changes (new phone, lost SIM): hard negatives for "new device" rules
    people = np.concatenate([pop.customers, pop.aged_mules])
    for rate, handler in ((cfg.legit_device_change_rate_per_month, _legit_device_change),
                          (cfg.legit_pin_reset_rate_per_month, _legit_pin_reset),
                          (cfg.legit_sim_replacement_rate_per_month, _legit_sim_replacement)):
        expected = rate * len(people) * cfg.days / 30
        for person in rng.choice(people, size=rng.poisson(expected)):
            sim.schedule(rng.integers(0, cfg.days * SECONDS_PER_DAY), handler, int(person))

    fraud.schedule_all(sim)
    if cfg.promo_start_day is not None and cfg.promo_new_phone_share > 0:
        # Separate random stream: everything before the promotion stays exactly as without it
        promo = np.random.default_rng(cfg.seed + 1)
        buyers = promo.choice(pop.customers, size=int(cfg.promo_new_phone_share * len(pop.customers)),
                              replace=False)
        start = cfg.promo_start_day * SECONDS_PER_DAY
        for person in buyers:
            sim.schedule(int(start + promo.integers(0, 7 * SECONDS_PER_DAY)), _legit_device_change, int(person))
    sim.run(plan)
    return _to_frames(sim)


def _to_frames(sim: Simulation) -> dict[str, pd.DataFrame]:
    pop, cfg = sim.pop, sim.cfg
    start = pd.Timestamp(cfg.start)
    names = np.array(pop.names)

    tx = pd.DataFrame({k: np.frombuffer(v, dtype=v.typecode) for k, v in sim.rows.items()})
    sim.rows.clear()
    tx = tx.sort_values("t", kind="stable").reset_index(drop=True)
    out = pd.DataFrame({
        "tx_id": np.arange(len(tx), dtype=np.int64),
        "timestamp": start + pd.to_timedelta(tx["t"], unit="s"),
        "type": pd.Categorical.from_codes(tx["type"], TYPES),
        "channel": pd.Categorical.from_codes(tx["channel"], CHANNELS),
        "status": pd.Categorical.from_codes(tx["status"], STATUSES),
        "amount": tx["amount"],
        "fee": tx["fee"].astype("float64"),
        "sender": pd.Categorical(names[tx["sender"]]),
        "receiver": pd.Categorical(names[tx["receiver"]]),
        "sender_balance_before": tx["sender_balance_before"],
        "sender_balance_after": tx["sender_balance_after"],
        "receiver_balance_before": tx["receiver_balance_before"],
        "receiver_balance_after": tx["receiver_balance_after"],
        "device": pd.Categorical(
            np.where(tx["device"] >= 0, "D" + tx["device"].astype(str).str.zfill(6), None)
        ),
        "is_fraud": (tx["scenario"] > 0).astype("int8"),
        # Code 0 means "legitimate": shown as missing
        "scenario": pd.Categorical.from_codes(tx["scenario"] - 1, SCENARIOS[1:]),
        "role": pd.Categorical.from_codes(tx["role"] - 1, ROLES[1:]),
        "strategy": pd.Categorical.from_codes(tx["strategy"] - 1, STRATEGIES[1:]),
        "attack_id": tx["attack_id"].astype("int32"),
    })

    events = pd.DataFrame(sim.account_events, columns=["t", "account", "event", "device"])
    events = events.sort_values("t", kind="stable").reset_index(drop=True)
    events = pd.DataFrame({
        "timestamp": start + pd.to_timedelta(events["t"], unit="s"),
        "account": names[events["account"].to_numpy(dtype=np.int64)] if len(events) else [],
        "event": events["event"],
        "device": "D" + events["device"].astype(str).str.zfill(6),
    })

    accounts = pd.DataFrame({
        "account": names,
        "kind": pd.Categorical.from_codes(pop.kind, KINDS),  # ground truth: never a model feature
        "profile": [pop.profile_names[p] if p >= 0 else None for p in pop.profile],
        "region": [pop.region_names[r] for r in pop.region],
        "opened": start + pd.to_timedelta(pop.opened_day, unit="D"),
        "rogue_agent": np.isin(np.arange(len(names)), pop.rogue_agents),
    })
    # Fresh mules that were never used were never opened
    accounts = accounts[accounts["opened"] <= start + pd.Timedelta(days=cfg.days)].reset_index(drop=True)
    return {"transactions": out, "account_events": events, "accounts": accounts}
