"""Fraud scenarios, each in a naive and an adaptive version.

Mechanics follow scams reported in Cameroon (sources in docs/simulator.md):

account_takeover
    The fraudster gets the PIN (a call from a fake "agent", or a code the victim was
    tricked into dialling) or swaps the victim's SIM, then moves the money to mule
    accounts that withdraw it at agents.
    naive:    acts within the hour, at any time of day, takes the whole balance in one
              transfer to a freshly opened mule, who withdraws everything at once.
    adaptive: waits hours, acts in business hours, "warms up" the new phone with a small
              airtime purchase, takes 50-90% in 2-4 round-number transfers to long-standing
              accounts, and the mules withdraw part of it later.

withdrawal_request
    A rogue agent sends withdrawal requests to many numbers; anyone who approves with
    their PIN by mistake loses the money. Most requests are declined.
    naive:    hundreds of requests in two hours, random numbers nationwide, fixed amounts.
    adaptive: fewer requests per hour over three days, local numbers, varied amounts.

wrong_transfer
    A fake SMS says the victim received money; a caller says it was a mistake and asks
    for it back. The victim sends real money for a credit that never happened. Some
    victims are also talked into dialling a code that leaks their PIN (-> takeover).
    naive:    a handful of scammer numbers reused for every victim, round amounts.
    adaptive: a different recipient each time, ordinary-looking amounts.

rented (takeovers and wrong transfers, only when FraudConfig.rented_share > 0)
    The money goes to an ordinary customer's account rented out to the fraudster: years of
    normal history, no sudden stream of strangers, and the money is not withdrawn quickly.
    Takeovers also wait one to three days and take small round amounts. Added after the
    game's scripted players showed the model was blind to it (reports/game_strategies.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from momofraud.sim.config import TRANSFER_TAX
from momofraud.sim.legit import SECONDS_PER_DAY, C, T

if TYPE_CHECKING:
    from momofraud.sim.engine import Label, Simulation

MIN_WORTH_STEALING = 2_000
MINUTE, HOUR = 60, 3600


def _label(scenario: str, role: str, strategy: str, attack_id: int) -> Label:
    from momofraud.sim.engine import Label
    return Label(scenario=scenario, role=role, strategy=strategy, attack_id=attack_id)


def _strategy(sim: Simulation, rented_allowed: bool = False) -> str:
    # The extra draw only happens when rented attacks are on, so other worlds don't change
    if rented_allowed and sim.cfg.fraud.rented_share > 0 and sim.rng.random() < sim.cfg.fraud.rented_share:
        return "rented"
    return "adaptive" if sim.rng.random() < sim.cfg.fraud.adaptive_share else "naive"


def _rented_account(sim: Simulation, exclude: int) -> int:
    """An ordinary customer's account, rented out to the fraudster."""
    while True:
        account = int(sim.rng.choice(sim.pop.customers))
        if account != exclude:
            return account


def _business_hours(sim: Simulation, t: float) -> float:
    """Move t to between 08:00 and 19:00 (same day, or the next morning)."""
    day, seconds = divmod(int(t), SECONDS_PER_DAY)
    if 8 * HOUR <= seconds < 19 * HOUR:
        return t
    if seconds >= 19 * HOUR:
        day += 1
    return day * SECONDS_PER_DAY + sim.rng.uniform(8 * HOUR, 12 * HOUR)


def _victim_weights(sim: Simulation, people: np.ndarray) -> np.ndarray:
    """Assumption: retired and rural users are targeted somewhat more often."""
    names = sim.pop.profile_names
    boost = {names.index("retired"): 2.0, names.index("farmer"): 1.5}
    w = np.array([boost.get(int(p), 1.0) for p in sim.pop.profile[people]])
    return w / w.sum()


def schedule_all(sim: Simulation) -> None:
    cfg, f, rng, pop = sim.cfg, sim.cfg.fraud, sim.rng, sim.pop
    months = cfg.days / 30
    horizon = cfg.days * SECONDS_PER_DAY
    customers = pop.customers
    weights = _victim_weights(sim, customers)

    n_takeovers = rng.poisson(f.takeovers_per_10k_users_per_month * cfg.n_users / 10_000 * months)
    for victim in rng.choice(customers, size=n_takeovers, p=weights):
        entry = "SIM_SWAP" if rng.random() < 0.4 else "PIN_RESET"
        sim.schedule(rng.uniform(0, horizon * 0.97), takeover_start, int(victim), _strategy(sim, True), entry)

    for _ in range(rng.poisson(f.withdrawal_campaigns_per_month * months)):
        agent = int(rng.choice(pop.rogue_agents))
        start = _business_hours(sim, rng.uniform(0, horizon * 0.95))
        _plan_withdrawal_campaign(sim, start, agent, _strategy(sim), sim.new_attack_id())

    n_wrong = rng.poisson(f.wrong_transfer_victims_per_10k_users_per_month * cfg.n_users / 10_000 * months)
    for victim in rng.choice(customers, size=n_wrong, p=weights):
        t = _business_hours(sim, rng.uniform(0, horizon * 0.97))
        sim.schedule(t, wrong_transfer, int(victim), _strategy(sim, True), sim.new_attack_id())


# -- account takeover ---------------------------------------------------------------------

def takeover_start(sim: Simulation, t: int, victim: int, strategy: str, entry: str,
                   attack_id: int | None = None) -> None:
    rng = sim.rng
    attack_id = sim.new_attack_id() if attack_id is None else attack_id
    attacker_device = sim.new_device()
    sim.record_account_event(t, victim, entry, attacker_device)
    if entry == "SIM_SWAP":
        # The owner loses service until the operator restores their SIM
        restored = t + rng.uniform(1, 3) * SECONDS_PER_DAY
        sim.blocked_until[victim] = int(restored)
        sim.schedule(restored, _sim_restored, victim)

    if strategy == "naive":
        sim.schedule(t + rng.uniform(5 * MINUTE, 60 * MINUTE), takeover_drain,
                     victim, attacker_device, strategy, attack_id, 1, 1, 1.0)
        return

    if strategy == "rented":
        # Patient: one to three days, a warm-up, then small round amounts to one rented account
        act_at = _business_hours(sim, t + rng.uniform(24 * HOUR, 72 * HOUR))
        if entry == "SIM_SWAP":
            act_at = max(t + HOUR, min(act_at, sim.blocked_until[victim] - HOUR))
        sim.schedule(act_at - rng.uniform(10 * MINUTE, 60 * MINUTE), _warmup, victim, attacker_device, attack_id)
        account = _rented_account(sim, victim)
        parts = int(rng.integers(3, 7))
        for i in range(parts):
            sim.schedule(act_at + i * rng.uniform(1 * HOUR, 3 * HOUR), takeover_drain,
                         victim, attacker_device, strategy, attack_id, i + 1, parts, 1.0, account)
        return

    act_at = _business_hours(sim, t + rng.uniform(2 * HOUR, 36 * HOUR))
    if entry == "SIM_SWAP":
        act_at = min(act_at, sim.blocked_until[victim] - HOUR)  # before the owner gets the SIM back
    sim.schedule(act_at - rng.uniform(10 * MINUTE, 60 * MINUTE), _warmup, victim, attacker_device, attack_id)
    parts = int(rng.integers(2, 5))
    share = rng.uniform(0.5, 0.9)
    mules = rng.choice(sim.pop.aged_mules, size=parts, replace=True)
    for i in range(parts):
        sim.schedule(act_at + i * rng.uniform(15 * MINUTE, 120 * MINUTE), takeover_drain,
                     victim, attacker_device, strategy, attack_id, i + 1, parts, share, int(mules[i]))


def _sim_restored(sim: Simulation, t: int, victim: int) -> None:
    sim.record_account_event(t, victim, "SIM_RESTORED", sim.device[victim])


def _warmup(sim: Simulation, t: int, victim: int, device: int, attack_id: int) -> None:
    """A small airtime purchase so the new phone has some normal-looking history."""
    amount = float(sim.rng.choice([500, 1000]))
    sim.transact(t, T["AIRTIME"], C["USSD"], victim, sim.pop.payee["AIRTIME"], amount,
                 device=device, label=_label("account_takeover", "warmup", "adaptive", attack_id))


def takeover_drain(sim: Simulation, t: int, victim: int, device: int, strategy: str, attack_id: int,
                   part: int, parts: int, share: float, mule: int | None = None) -> None:
    rng = sim.rng
    balance = sim.balance[victim]
    if strategy == "naive":
        amount = np.floor(balance / (1 + TRANSFER_TAX))  # everything, after the transfer tax
        mule = _fresh_mule(sim, t)
    elif strategy == "rented":
        amount = float(rng.choice([2_000, 3_000, 5_000, 5_000, 10_000]))
        amount = min(amount, np.floor(balance * 0.9 / 500) * 500)
    else:
        # The total to steal is fixed when the first part runs, from the balance at that moment
        if part == 1:
            sim.takeover_targets[attack_id] = balance * share
        planned = sim.takeover_targets.get(attack_id, 0.0) / parts
        amount = min(planned * rng.uniform(0.85, 1.15), balance * 0.95)
        amount = np.floor(amount / 500) * 500  # round numbers look like normal transfers
    if amount < MIN_WORTH_STEALING:
        return
    channel = C["APP"] if strategy == "adaptive" and rng.random() < 0.5 else C["USSD"]
    sim.transact(t, T["TRANSFER"], channel, victim, int(mule), float(amount), device=device,
                 label=_label("account_takeover", "victim_debit", strategy, attack_id))


def _fresh_mule(sim: Simulation, t: int) -> int:
    """A mule account opened in the last few days (naive fraudsters burn through them)."""
    pop, rng = sim.pop, sim.rng
    day = t // SECONDS_PER_DAY
    unused = pop.fresh_mules[pop.opened_day[pop.fresh_mules] > sim.cfg.days]
    recent = pop.fresh_mules[(pop.opened_day[pop.fresh_mules] <= day) &
                             (pop.opened_day[pop.fresh_mules] >= day - 7)]
    if len(recent) and (rng.random() < 0.5 or not len(unused)):
        return int(rng.choice(recent))
    mule = int(rng.choice(unused if len(unused) else pop.fresh_mules))
    pop.opened_day[mule] = min(pop.opened_day[mule], day - int(rng.integers(0, 6)))
    return mule


# -- what happens to stolen money ---------------------------------------------------------------

def on_fraud_credit(sim: Simulation, t: int, receiver: int, amount: float, label: Label) -> None:
    """Mules and scammers withdraw what they receive."""
    if not sim.pop.tracked[receiver] or label.role != "victim_debit" or label.strategy == "rented":
        return  # rented accounts let the money sit
    rng = sim.rng
    if label.strategy == "naive":
        delay, share = rng.uniform(5 * MINUTE, 30 * MINUTE), 1.0
        agent = int(rng.choice(sim.pop.agents))
    else:
        delay, share = rng.uniform(1 * HOUR, 12 * HOUR), rng.uniform(0.6, 0.9)
        agent = int(rng.choice(sim.pop.home_agents[receiver]))
    if label.scenario == "wrong_transfer" and label.strategy == "naive":
        # Scammers collect several refunds before withdrawing
        if sim.balance[receiver] < 20_000:
            return
        delay = rng.uniform(1 * HOUR, 4 * HOUR)
    sim.schedule(t + delay, _mule_cash_out, receiver, agent, share, label)


def _mule_cash_out(sim: Simulation, t: int, mule: int, agent: int, share: float, label: Label) -> None:
    amount = np.floor(sim.balance[mule] * share / (1 + TRANSFER_TAX) / 500) * 500
    if amount < 500:
        return
    channel = C["AGENT_REQUEST"] if sim.rng.random() < 0.6 else C["USSD"]
    sim.transact(t, T["CASH_OUT"], channel, mule, agent, float(amount),
                 label=_label(label.scenario, "mule_cashout", label.strategy, label.attack_id))


# -- unsolicited withdrawal requests --------------------------------------------------------

def _plan_withdrawal_campaign(
    sim: Simulation, start: float, agent: int, strategy: str, attack_id: int
) -> None:
    rng, pop = sim.rng, sim.pop
    if strategy == "naive":
        n = 300
        times = start + np.sort(rng.uniform(0, 2 * HOUR, size=n))
        targets = rng.choice(pop.customers, size=n)
        amounts = rng.choice([25_000.0, 50_000.0], size=n)
    else:
        n = 180
        days = np.repeat(np.arange(3), 60)
        times = np.array([_business_hours(sim, start + d * SECONDS_PER_DAY + rng.uniform(0, 9 * HOUR))
                          for d in days])
        local = pop.customers[pop.region[pop.customers] == pop.region[agent]]
        targets = rng.choice(local if len(local) else pop.customers, size=n)
        amounts = np.maximum(np.round(rng.lognormal(np.log(10_000), 0.6, size=n) / 500) * 500, 1_000)
    for when, target, amount in zip(times, targets, amounts, strict=True):
        sim.schedule(when, withdrawal_request, agent, int(target), float(amount), strategy, attack_id)


def withdrawal_request(sim: Simulation, t: int, agent: int, target: int, amount: float,
                       strategy: str, attack_id: int) -> None:
    names = sim.pop.profile_names
    vulnerable = sim.pop.profile[target] in (names.index("retired"), names.index("farmer"))
    approves = sim.rng.random() < (0.08 if vulnerable else 0.04)
    role = "victim_debit" if approves else "attempt"
    sim.transact(t, T["CASH_OUT"], C["AGENT_REQUEST"], target, agent, amount,
                 device=sim.device[target], declined=not approves,
                 label=_label("withdrawal_request", role, strategy, attack_id))


# -- "I sent you money by mistake" ----------------------------------------------------------

def wrong_transfer(sim: Simulation, t: int, victim: int, strategy: str, attack_id: int) -> None:
    rng, pop, f = sim.rng, sim.pop, sim.cfg.fraud
    if strategy == "naive":
        scammer = int(rng.choice(pop.scammers))
        amount = float(rng.choice([1_000, 2_000, 5_000, 10_000]))
    elif strategy == "rented":
        scammer = _rented_account(sim, victim)
        amount = float(rng.choice([2_000, 5_000, 5_000, 15_000]))
    else:
        scammer = int(rng.choice(pop.aged_mules))
        amount = float(max(500, round(rng.lognormal(np.log(4_000), 0.7) / 25) * 25))
    sim.transact(t, T["TRANSFER"], C["USSD"], victim, scammer, amount, device=sim.device[victim],
                 label=_label("wrong_transfer", "victim_debit", strategy, attack_id))
    if rng.random() < f.wrong_transfer_code_leak:
        # The "refund code" the caller dictated actually leaked the victim's PIN
        sim.schedule(t + rng.uniform(10 * MINUTE, 60 * MINUTE), takeover_start, victim, strategy, "PIN_RESET")
