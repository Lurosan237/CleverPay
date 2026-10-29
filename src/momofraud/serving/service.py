"""Score, decide, explain and apply one transaction.

Shared by the HTTP API and the game, so both make exactly the same decisions.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import numpy as np

from momofraud.behaviour import FEATURES
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network, NetworkError
from momofraud.serving.reasons import reasons

SCORED_TYPES = {"TRANSFER", "CASH_OUT"}


@dataclass
class Outcome:
    transaction_id: int | None
    timestamp: str
    decision: str          # approve | review | block | not_scored | declined_by_customer
    status: str            # SUCCESS | FAILED_FUNDS | BLOCKED | HELD_FOR_REVIEW | DECLINED | NOT_COMMITTED
    score: float | None
    reasons: list[dict] = field(default_factory=list)
    contributions: list[dict] = field(default_factory=list)
    sender_balance: float | None = None
    timings_us: dict[str, float] = field(default_factory=dict)
    features: list[float] | None = None  # kept for logging; not part of the API response

    def public(self) -> dict:
        out = self.__dict__.copy()
        out.pop("features")
        return out


def process(net: Network, model: FraudModel, *, type_: str, channel: str, sender: str, receiver: str,
            amount: float, device: str | None, t: int, customer_declined: bool = False,
            override_review: bool = False, explain: bool = False, lang: str = "en",
            commit: bool = True) -> Outcome:
    started = time.perf_counter_ns()
    record = net.build(type_, channel, sender, receiver, amount, device, t)
    timings: dict[str, float] = {}

    def done(decision: str, status: str, score: float | None = None, why=(), contrib=(), features=None) -> Outcome:
        timings["total"] = (time.perf_counter_ns() - started) / 1000
        return Outcome(
            transaction_id=net.next_id if commit and status != "NOT_COMMITTED" else None,
            timestamp=net.timestamp(t), decision=decision, status=status, score=score,
            reasons=list(why), contributions=list(contrib), sender_balance=net.balance.get(sender),
            timings_us={k: round(v, 1) for k, v in timings.items()}, features=features)

    if customer_declined:
        if not (type_ == "CASH_OUT" and channel == "AGENT_REQUEST"):
            raise NetworkError("customer_declined only applies to CASH_OUT with channel AGENT_REQUEST")
        if commit:
            net.apply(record, "DECLINED")
        return done("declined_by_customer", "DECLINED" if commit else "NOT_COMMITTED")

    if type_ not in SCORED_TYPES:
        status = net.apply(record, "SUCCESS") if commit else "NOT_COMMITTED"
        return done("not_scored", status)

    tick = time.perf_counter_ns()
    features = net.state.features(record)
    timings["features"] = (time.perf_counter_ns() - tick) / 1000
    tick = time.perf_counter_ns()
    probability = model.probability(features)
    timings["model"] = (time.perf_counter_ns() - tick) / 1000
    decision = model.decide(probability)

    why, contrib = [], []
    if decision != "approve" or explain:
        tick = time.perf_counter_ns()
        explanation = model.explain(features)
        why = reasons(explanation.contributions, features, lang=lang)
        order = np.argsort(-np.abs(explanation.contributions))[:8]
        contrib = [{"feature": FEATURES[i], "value": round(float(features[i]), 4),
                    "contribution": round(float(explanation.contributions[i]), 4)} for i in order]
        timings["explain"] = (time.perf_counter_ns() - tick) / 1000

    if not commit:
        status = "NOT_COMMITTED"
    elif decision == "block":
        status = net.apply(record, "BLOCKED")
    elif decision == "review" and not override_review:
        status = net.apply(record, "HELD_FOR_REVIEW")
    else:
        status = net.apply(record, "SUCCESS")
    return done(decision, status, round(probability, 6), why, contrib, features)


def new_number(net: Network, seed: int | None = None) -> str:
    """A fresh, unused phone-number-like account id."""
    rng = random.Random(len(net.kind) if seed is None else seed)
    while True:
        number = f"69{rng.randrange(10**7):07d}"
        if number not in net.kind:
            return number
