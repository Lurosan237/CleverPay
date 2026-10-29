"""Drift monitoring: is the traffic the model sees still like the traffic it was tuned on?

    python -m momofraud.monitoring reference   # models/drift_reference.json (from the mixed world)
    python -m momofraud.monitoring report      # reports/drift.md and .json (needs the promo world)

What is watched, and why each check exists:

1. **Distribution shift, per feature**: the Population Stability Index (PSI) between the
   reference and recent traffic. Rule of thumb: below 0.1 stable, 0.1-0.25 watch, above 0.25
   a real shift.
2. **Rare-event jumps**: PSI barely moves when something rare becomes three times as common
   (new phones going from 0.06% to 2% of transactions gives a PSI under 0.1), yet that is
   exactly the change that matters for fraud features. So every bin is also tested on its own:
   flagged when it is at least twice as common as in the reference *and* the difference is
   more than 5 standard errors away from chance.
3. **Score shift**: PSI of the model's output. If it moves, the alert thresholds no longer mean
   what they meant.
4. **Alert rates**: the share of transactions held for review or blocked. Reported separately
   from drift: a jump is often an attack, not a change in customers.

Counters that grow with an account's age (lifetime transactions, account age...) are expected
to rise in a young network, and in this 90-day simulation that starts empty they always do.
They are reported but don't raise the status.

None of this needs labels, so it works the same day. Confirmed fraud arrives weeks later (after
complaints and investigations); the offline report adds precision and recall from the labels,
but a live system can't wait for them.

The reference is the mixed world's validation days: the most recent data before the model
went live, scored out of sample, and the period the alert thresholds were chosen on.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from momofraud.behaviour import FEATURES
from momofraud.paths import MODELS_DIR, REPORTS_DIR

REFERENCE_FILE = MODELS_DIR / "drift_reference.json"
WATCH, DRIFT = 0.10, 0.25
JUMP_RATIO, JUMP_Z = 2.0, 5.0
EPS = 1e-4  # stands in for an empty bin, so PSI stays finite
# Grow as accounts age: expected to rise, so they don't raise the status
GROWING = {"sender_history", "sender_age_days", "device_history", "hours_since_device_first_seen",
           "pair_history", "receiver_age_days", "receiver_history"}


# -- PSI -----------------------------------------------------------------------------------------

def bin_edges(values: np.ndarray, bins: int = 10) -> list[float]:
    """Inner bin edges at the deciles, merged when equal. Edges are actual data values, so a binary
    feature gets the edges {0, 1}: one bin for 0 and one for 1."""
    edges = np.unique(np.quantile(values, np.linspace(0, 1, bins + 1)[1:-1], method="nearest"))
    return [float(e) for e in edges]


def proportions(values: np.ndarray, edges: list[float]) -> np.ndarray:
    """Share of values in each bin: (-inf, e0], (e0, e1], ..., (e_last, inf)."""
    idx = np.searchsorted(np.asarray(edges), values, side="left")
    return np.bincount(idx, minlength=len(edges) + 1) / max(len(values), 1)


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    e, a = np.clip(expected, EPS, None), np.clip(actual, EPS, None)
    return float(np.sum((a - e) * np.log(a / e)))


def jumps(expected: np.ndarray, actual: np.ndarray, n: int) -> list[tuple[int, float, float]]:
    """Bins at least JUMP_RATIO times as common as expected, JUMP_Z standard errors from chance."""
    e = np.clip(expected, EPS, None)
    z = (actual - e) / np.sqrt(np.clip(e * (1 - e), EPS, None) / max(n, 1))
    return [(int(b), float(z[b]), float(actual[b] / e[b])) for b in np.where((actual >= JUMP_RATIO * e) &
                                                                                (z >= JUMP_Z))[0]]


def bin_label(edges: list[float], b: int) -> str:
    def f(v):
        return f"{v:.3g}"
    if not edges:
        return "all"
    if b == 0:
        return f"<= {f(edges[0])}"
    if b == len(edges):
        return f"> {f(edges[-1])}"
    if b == 1 and edges[0] == 0 and edges[1] == 1:
        return "= 1"
    return f"{f(edges[b - 1])} to {f(edges[b])}"


def level(value: float) -> str:
    return "drift" if value >= DRIFT else "watch" if value >= WATCH else "stable"


# -- reference -----------------------------------------------------------------------------------

@dataclass
class Reference:
    features: dict[str, dict]   # name -> {"edges": [...], "expected": [...]}
    score: dict                 # {"edges": [...], "expected": [...]} on log10(score)
    review_rate: float
    block_rate: float
    rows: int
    source: str

    @classmethod
    def build(cls, x: np.ndarray, scores: np.ndarray, review: float, block: float, source: str) -> Reference:
        feats = {}
        for i, name in enumerate(FEATURES):
            edges = bin_edges(x[:, i])
            feats[name] = {"edges": edges, "expected": proportions(x[:, i], edges).round(6).tolist()}
        log_scores = np.log10(np.clip(scores, 1e-6, 1))
        edges = bin_edges(log_scores, bins=20)
        return cls(features=feats, score={"edges": edges, "expected": proportions(log_scores, edges).round(6).tolist()},
                   review_rate=float(np.mean(scores >= review)), block_rate=float(np.mean(scores >= block)),
                   rows=len(scores), source=source)

    def save(self, path: Path = REFERENCE_FILE) -> None:
        path.write_text(json.dumps(self.__dict__, indent=1))

    @classmethod
    def load(cls, path: Path = REFERENCE_FILE) -> Reference:
        return cls(**json.loads(Path(path).read_text()))

    # -- comparing a batch of traffic against the reference -------------------------------------
    def compare(self, x: np.ndarray, scores: np.ndarray, review: float, block: float) -> dict:
        n = len(scores)
        feats, rate_jumps = {}, []
        for i, (name, ref) in enumerate(self.features.items()):
            expected, actual = np.asarray(ref["expected"]), proportions(x[:, i], ref["edges"])
            feats[name] = psi(expected, actual)
            if name not in GROWING:
                rate_jumps += [{"feature": name, "values": bin_label(ref["edges"], b),
                                "expected": round(float(expected[b]), 5), "actual": round(float(actual[b]), 5),
                                "ratio": round(ratio, 1), "z": round(z, 1)}
                               for b, z, ratio in jumps(expected, actual, n)]
        log_scores = np.log10(np.clip(scores, 1e-6, 1))
        score_psi = psi(np.asarray(self.score["expected"]), proportions(log_scores, self.score["edges"]))
        review_rate, block_rate = float(np.mean(scores >= review)), float(np.mean(scores >= block))
        watched = {f: v for f, v in feats.items() if f not in GROWING}
        worst = max(max(watched.values()), score_psi)
        status = "drift" if worst >= DRIFT or rate_jumps else "watch" if worst >= WATCH else "stable"
        # Alert rate: a jump that chance can't explain (binomial, 3 standard errors) and at least 1.5x
        expected_reviews = self.review_rate * n
        alerts_high = (review_rate >= 1.5 * self.review_rate and
                       review_rate * n - expected_reviews >= 3 * np.sqrt(max(expected_reviews, 1)))
        return {
            "rows": n, "status": status,
            "rate_jumps": sorted(rate_jumps, key=lambda r: -r["z"])[:5],
            "top_features": [{"feature": f, "psi": round(v, 4), "level": level(v)}
                             for f, v in sorted(watched.items(), key=lambda kv: -kv[1])[:5]],
            "growing_features": {f: round(feats[f], 4) for f in sorted(GROWING)},
            "score_psi": round(score_psi, 4),
            "alerts": "high" if alerts_high else "normal",
            "review_rate": round(review_rate, 5), "block_rate": round(block_rate, 5),
            "reference_review_rate": round(self.review_rate, 5), "reference_block_rate": round(self.block_rate, 5),
            "feature_psi": {f: round(v, 4) for f, v in feats.items()},
        }


# -- live monitor (used by the API) --------------------------------------------------------------

class DriftMonitor:
    """Keeps the last `window` scored transactions and compares them with the reference."""

    def __init__(self, reference: Reference, review: float, block: float, window: int = 5000,
                 min_rows: int = 500):
        self.reference, self.review, self.block = reference, review, block
        self.min_rows = min_rows
        self.features: deque = deque(maxlen=window)
        self.scores: deque = deque(maxlen=window)
        self.seen = 0

    def update(self, features: list[float], score: float) -> None:
        self.features.append(features)
        self.scores.append(score)
        self.seen += 1

    def report(self) -> dict:
        base = {"window": self.features.maxlen, "rows_in_window": len(self.scores), "scored_since_start": self.seen,
                "reference": self.reference.source, "thresholds": {"watch": WATCH, "drift": DRIFT}}
        if len(self.scores) < self.min_rows:
            return base | {"status": "warming_up",
                           "detail": f"needs {self.min_rows} scored transactions, has {len(self.scores)}"}
        result = self.reference.compare(np.asarray(self.features), np.asarray(self.scores), self.review, self.block)
        result.pop("rows")
        return base | result


# -- offline: building the reference and the drift report ----------------------------------------

def build_reference() -> Reference:
    from momofraud.experiments import load_dataset
    from momofraud.serving.model import FraudModel

    model = FraudModel()
    x, _, _ = load_dataset("mixed").select("validation")
    values = x[FEATURES].to_numpy(dtype=np.float64)
    scores = model.booster.predict(values)
    return Reference.build(values, scores, model.review, model.block, source="mixed world, validation days 60-74")


WORLDS = {
    "mixed": "Same world as training (control): nothing changes",
    "adaptive": "Fraudsters switch to adaptive tactics: the scams change, the customers don't",
    "promo": "Phone promotion from day 78: a quarter of customers get a new phone within a week",
}


def drift_report(reference: Reference) -> dict:
    from momofraud.experiments import load_dataset
    from momofraud.serving.model import FraudModel

    model = FraudModel()
    out = {}
    for world in WORLDS:
        data = load_dataset(world)
        days = []
        for day in range(60, int(data.day.max()) + 1):
            mask = data.day == day
            x = data.x[mask][FEATURES].to_numpy(dtype=np.float64)
            y = data.y[mask]
            scores = model.booster.predict(x)
            row = reference.compare(x, scores, model.review, model.block)
            flagged = scores >= model.review
            row |= {"day": day, "fraud_rows": int(y.sum()),
                    "false_alarms_per_10k": round(float(np.mean(flagged & (y == 0)) * 1e4), 1),
                    "review_precision": round(float(y[flagged].mean()), 4) if flagged.any() else None,
                    "review_recall": round(float(flagged[y == 1].mean()), 4) if y.any() else None}
            row.pop("feature_psi")
            days.append(row)
        out[world] = days
        print(world, " ".join(f"{d['day']}:{d['status'][0]}" for d in days))
    return out


def _moved(d: dict) -> str:
    if d["rate_jumps"]:
        j = d["rate_jumps"][0]
        return f"{j['feature']} {j['values']}: {j['expected']:.2%} → {j['actual']:.2%}"
    top = d["top_features"][0]
    return f"{top['feature']} (PSI {top['psi']:.2f})" if top["psi"] >= WATCH else "-"


def to_markdown(report: dict) -> str:
    lines = ["# Drift monitoring", "",
             "Generated by `python -m momofraud.monitoring report`. Reference: the mixed world's validation days",
             "(60-74). Each row compares one day of traffic (about 13,000 transfers and withdrawals) with the",
             "reference. False alarms, precision and recall need fraud labels, which a live system only gets",
             "weeks later: the monitor itself never uses them.", ""]
    for world, days in report.items():
        flagged = [d["day"] for d in days if d["status"] == "drift"]
        lines += [f"## {world}: {WORLDS[world]}", "",
                  f"Days flagged as drift: {', '.join(map(str, flagged)) or 'none'}.", "",
                  "| Day | Status | What moved | Score PSI | Review rate | Alerts | False alarms / 10k | Recall |",
                  "|---|---|---|---|---|---|---|---|"]
        for d in days:
            if d["day"] < 75:
                continue  # validation days are the reference itself
            rec = "-" if d["review_recall"] is None else f"{d['review_recall']:.0%}"
            lines.append(f"| {d['day']} | {d['status']} | {_moved(d)} | {d['score_psi']:.3f} | "
                         f"{d['review_rate']:.2%} | {d['alerts']} | {d['false_alarms_per_10k']:.1f} | {rec} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    command = (argv if argv is not None else sys.argv[1:] or ["reference"])[0]
    if command == "reference":
        reference = build_reference()
        reference.save()
        print(f"reference from {reference.rows:,} rows: review rate {reference.review_rate:.3%}, "
              f"block rate {reference.block_rate:.3%} -> {REFERENCE_FILE}")
    elif command == "report":
        report = drift_report(Reference.load())
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "drift.json").write_text(json.dumps(report, indent=1))
        (REPORTS_DIR / "drift.md").write_text(to_markdown(report), encoding="utf-8")
    else:
        raise SystemExit("usage: python -m momofraud.monitoring [reference|report]")


if __name__ == "__main__":
    main()
