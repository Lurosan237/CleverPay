"""Planned legitimate activity: what each person *intends* to do over the period.

Planning is vectorised and ignores balances; the engine then executes the plan in
time order and fails transactions the sender can't afford, as a real system would.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from momofraud.sim.config import HOURLY_WEIGHTS, PROFILES, SimConfig
from momofraud.sim.population import Population

TYPES = ("CASH_IN", "CASH_OUT", "TRANSFER", "PAYMENT", "AIRTIME", "BILL", "SALARY")
CHANNELS = ("AGENT", "AGENT_REQUEST", "USSD", "APP")
T = {name: i for i, name in enumerate(TYPES)}
C = {name: i for i, name in enumerate(CHANNELS)}

SECONDS_PER_DAY = 86_400
HOUR_P = np.array(HOURLY_WEIGHTS) / np.sum(HOURLY_WEIGHTS)


def day_weights(cfg: SimConfig) -> np.ndarray:
    """Sundays are quieter (weight 0.6)."""
    dates = pd.date_range(cfg.start, periods=cfg.days, freq="D")
    weights = np.where(dates.dayofweek == 6, 0.6, 1.0)
    return weights / weights.sum()


def random_times(rng, n: int, cfg: SimConfig, days: np.ndarray | None = None) -> np.ndarray:
    if days is None:
        days = rng.choice(cfg.days, size=n, p=day_weights(cfg))
    hours = rng.choice(24, size=n, p=HOUR_P)
    return (days * SECONDS_PER_DAY + hours * 3600 + rng.integers(0, 3600, size=n)).astype(np.int64)


def round_amounts(rng, amounts: np.ndarray, step_small: int = 25) -> np.ndarray:
    """People mostly send round numbers: 60% rounded to 500 FCFA, the rest to 25."""
    round_500 = rng.random(len(amounts)) < 0.6
    out = np.where(round_500, np.round(amounts / 500) * 500, np.round(amounts / step_small) * step_small)
    return np.maximum(out, 100.0)


def plan_legit(pop: Population, cfg: SimConfig, rng: np.random.Generator) -> pd.DataFrame:
    people = np.concatenate([pop.customers, pop.aged_mules])
    activity, wealth = pop.activity, pop.wealth
    parts = []

    for p_index, prof in enumerate(PROFILES.values()):
        members = people[pop.profile[people] == p_index]
        if len(members) == 0:
            continue
        spend_scale = budget_scale(prof)
        for kind, (rate, median, sigma) in (
            ("CASH_IN", prof.cash_in), ("TRANSFER", prof.transfer), ("AIRTIME", prof.airtime),
            ("PAYMENT", prof.merchant), ("CASH_OUT", prof.cash_out),
        ):
            if kind in SPENDING:
                rate *= spend_scale
            counts = rng.poisson(rate * cfg.days * activity[members])
            who = np.repeat(members, counts)
            n = len(who)
            if n == 0:
                continue
            raw = rng.lognormal(np.log(median), sigma, size=n) * wealth[who]
            if kind == "AIRTIME":
                amount = np.maximum(np.round(raw / 100) * 100, 100.0)
            else:
                amount = round_amounts(rng, raw)
            parts.append(_route(kind, who, amount, random_times(rng, n, cfg), pop, rng))

        if prof.monthly_income:
            parts.append(_salaries(members, prof.monthly_income * wealth[members], pop, cfg, rng))
        for bill_index, bill in enumerate(prof.bills):
            parts.append(_bills(members, bill * wealth[members], bill_index, pop, cfg, rng))

    plan = pd.concat(parts, ignore_index=True).sort_values("t", kind="stable").reset_index(drop=True)
    return plan


SPENDING = ("AIRTIME", "PAYMENT", "CASH_OUT")
BUDGET_RATIO = 1.35  # tuned so typical balances stay roughly stable over the period


def _mean(rate: float, median: float, sigma: float) -> float:
    """Expected daily amount for a Poisson rate and lognormal amounts."""
    return rate * median * np.exp(sigma**2 / 2)


def budget_scale(prof) -> float:
    """Factor applied to spending rates (airtime, shops, withdrawals) so that, on average,
    a person's money out matches their money in.

    Money in: deposits, salary, and the transfers an average person receives. Money out:
    bills, the person's own transfers to family and friends, and spending. People in
    profiles that send a lot (salaried workers, traders) therefore spend less elsewhere.
    """
    received = sum(p.share * _mean(*p.transfer) for p in PROFILES.values()) / sum(
        p.share for p in PROFILES.values())
    money_in = _mean(*prof.cash_in) + prof.monthly_income / 30 + received
    fixed_out = sum(prof.bills) * 0.85 / 30 + _mean(*prof.transfer)
    spending = sum(_mean(*getattr(prof, k)) for k in ("airtime", "merchant", "cash_out"))
    return max(0.05, (BUDGET_RATIO * money_in - fixed_out) / spending)


def _route(
    kind: str, who: np.ndarray, amount: np.ndarray, t: np.ndarray, pop: Population, rng
) -> pd.DataFrame:
    n = len(who)
    sender, receiver = who.copy(), who.copy()
    channel = np.full(n, C["USSD"], dtype=np.int8)
    declined = np.zeros(n, dtype=bool)

    if kind in ("CASH_IN", "CASH_OUT"):
        agent = _pick_agents(who, pop, rng)
        if kind == "CASH_IN":
            sender = agent
            channel[:] = C["AGENT"]
        else:
            receiver = agent
            # Withdrawals: the agent sends a request the customer approves with their PIN
            # (60%), or the customer starts it themselves. A few requests are declined (typos).
            by_request = rng.random(n) < 0.6
            channel = np.where(by_request, C["AGENT_REQUEST"], C["USSD"]).astype(np.int8)
            declined = by_request & (rng.random(n) < 0.02)
    elif kind == "TRANSFER":
        receiver = _pick_recipients(who, pop, rng)
        channel = np.where(rng.random(n) < 0.3, C["APP"], C["USSD"]).astype(np.int8)
    elif kind == "AIRTIME":
        receiver = np.full(n, pop.payee["AIRTIME"])
    elif kind == "PAYMENT":
        receiver = _pick_shops(who, pop, rng)
        channel = np.where(rng.random(n) < 0.4, C["APP"], C["USSD"]).astype(np.int8)
    return pd.DataFrame({
        "t": t, "type": np.int8(T[kind]), "channel": channel, "sender": sender, "receiver": receiver,
        "amount": amount, "declined": declined,
    })


def _pick_agents(who, pop: Population, rng) -> np.ndarray:
    """Usually one of the person's two usual agents, sometimes any agent (travelling)."""
    usual = np.array([pop.home_agents[w][rng.integers(len(pop.home_agents[w]))] for w in who])
    elsewhere = rng.choice(pop.agents, size=len(who))
    return np.where(rng.random(len(who)) < 0.9, usual, elsewhere)


def _pick_recipients(who, pop: Population, rng) -> np.ndarray:
    """88% to someone in their usual circle, otherwise to a stranger (a one-off payment)."""
    out = np.empty(len(who), dtype=np.int64)
    stranger = rng.random(len(who)) >= 0.88
    strangers = rng.choice(pop.customers, size=len(who))
    for i, w in enumerate(who):
        circle = pop.contacts[w]
        out[i] = strangers[i] if stranger[i] or len(circle) == 0 else circle[rng.integers(len(circle))]
        while out[i] == w:  # never yourself
            out[i] = rng.choice(pop.customers)
    return out


def _pick_shops(who, pop: Population, rng) -> np.ndarray:
    shops_by_region = {r: pop.shops[pop.region[pop.shops] == r] for r in np.unique(pop.region[pop.shops])}
    out = rng.choice(pop.shops, size=len(who))
    local = rng.random(len(who)) < 0.85
    for i in np.where(local)[0]:
        pool = shops_by_region.get(pop.region[who[i]])
        if pool is not None and len(pool):
            out[i] = pool[rng.integers(len(pool))]
    return out


def _month_days(cfg: SimConfig) -> list[np.ndarray]:
    dates = pd.date_range(cfg.start, periods=cfg.days, freq="D")
    months = sorted(set(zip(dates.year, dates.month, strict=True)))
    return [np.where((dates.year == y) & (dates.month == m))[0] for y, m in months]


def _salaries(members, amounts, pop: Population, cfg: SimConfig, rng) -> pd.DataFrame:
    """Paid on one of the last three days of each month the simulation fully covers."""
    rows = []
    for days in _month_days(cfg):
        if len(days) < 28:
            continue
        pay_day = rng.choice(days[-3:], size=len(members))
        t = pay_day * SECONDS_PER_DAY + rng.integers(8 * 3600, 17 * 3600, size=len(members))
        rows.append(pd.DataFrame({
            "t": t.astype(np.int64), "type": np.int8(T["SALARY"]), "channel": np.int8(C["APP"]),
            "sender": pop.external, "receiver": members,
            "amount": np.round(amounts * rng.normal(1, 0.03, size=len(members)), -2), "declined": False,
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _bills(members, amounts, bill_index: int, pop: Population, cfg: SimConfig, rng) -> pd.DataFrame:
    payee = pop.payee["ELECTRICITY" if bill_index == 0 else "TV"]
    rows = []
    for days in _month_days(cfg):
        pays = rng.random(len(members)) < 0.85  # not everyone pays by mobile money every month
        who = members[pays]
        rows.append(pd.DataFrame({
            "t": random_times(rng, len(who), cfg, days=rng.choice(days, size=len(who))),
            "type": np.int8(T["BILL"]), "channel": np.int8(C["USSD"]), "sender": who,
            "receiver": payee, "amount": np.round(amounts[pays] * rng.lognormal(0, 0.2, size=len(who)), -2),
            "declined": False,
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
