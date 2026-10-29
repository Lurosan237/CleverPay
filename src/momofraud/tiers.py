"""The four models behind the game's difficulty levels, each a real model with real metrics.

    python -m momofraud.tiers     # models/tiers/*.txt, models/tiers/tiers.json, reports/tiers.md

Needs the mixed, adaptive and patched worlds (and their features):

    python -m momofraud.sim --adaptive-share 0.5 --rented-share 0.35 --name patched
    python -m momofraud.featurestore patched

| Level   | What the model knows                                         | Trained on            |
|---------|--------------------------------------------------------------|-----------------------|
| Rookie  | the transaction alone (amount, balance, time...)             | mixed world           |
| Analyst | + the sender's habits and whether they paid this person before | mixed world         |
| Expert  | all 33 features: devices, receivers, agents (production model) | mixed + adversarial  |
| Elite   | the same, retrained on the rented-account blind spot          | patched + adversarial |

Every model's alert thresholds are chosen on its own training world's validation days (90%
precision to block, 50% to review), never on the test days. All are tested on days 75-89 of
the adaptive world (the stage 3 benchmark) and of the patched world (which has the rented-
account attacks).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import lightgbm as lgb

from momofraud.behaviour import FEATURE_GROUPS, FEATURES
from momofraud.experiments import adversarial_copies, evaluate, load_dataset, scenario_rows, train_lightgbm
from momofraud.metrics import threshold_for_precision
from momofraud.paths import MODELS_DIR, REPORTS_DIR
from momofraud.train import BLOCK_PRECISION, MODEL_FILE, REVIEW_PRECISION

TIERS_DIR = MODELS_DIR / "tiers"
G = FEATURE_GROUPS
TIERS = {
    "rookie": {"name": "Rookie", "features": G["transaction"], "world": "mixed",
               "knows": "The transaction alone: amount, balance, time of day."},
    "analyst": {"name": "Analyst", "features": G["transaction"] + G["sender"] + G["recipient"], "world": "mixed",
                "knows": "Also the sender's habits and whether they have paid this person before."},
    "expert": {"name": "Expert", "features": FEATURES, "world": "mixed", "production": True,
               "knows": "All 33 behavioural features: phones, SIM swaps, receiving accounts, agents."},
    "elite": {"name": "Elite", "features": FEATURES, "world": "patched",
              "knows": "The same features, retrained on rented-account attacks after the game exposed them."},
}


def _scores(booster: lgb.Booster, x, features):
    return booster.predict(x[features].to_numpy(dtype="float64"))


def run() -> dict:
    worlds = {name: load_dataset(name) for name in ("mixed", "adaptive", "patched")}
    TIERS_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, tier in TIERS.items():
        train_world, features = worlds[tier["world"]], tier["features"]
        if tier.get("production"):
            booster = lgb.Booster(model_file=str(MODEL_FILE))
        else:
            extra = adversarial_copies(train_world) if features == FEATURES else None
            booster = train_lightgbm(train_world, features, extra=extra).booster_
        x_va, y_va, _ = train_world.select("validation")
        val = _scores(booster, x_va, features)
        block = threshold_for_precision(y_va, val, BLOCK_PRECISION)
        review = min(threshold_for_precision(y_va, val, REVIEW_PRECISION), block)
        tests = {}
        for test_name in ("adaptive", "patched"):
            x_te, y_te, scenario = worlds[test_name].select("test")
            scores = _scores(booster, x_te, features)
            tests[test_name] = {}
            for level, threshold in (("block", block), ("review", review)):
                r = evaluate(scores, y_te, scenario, threshold)
                tests[test_name][level] = {
                    "precision": round(r["precision_at_threshold"], 4),
                    "recall": round(r["recall_at_threshold"], 4),
                    "false_alarms_per_10k": round(r["false_alarms_per_10k"], 2),
                    "recall_by_scenario": {k: round(v, 4) for k, v in scenario_rows(r).items()},
                    "recall_by_strategy": {k: round(v["caught"], 4) for k, v in r["by_scenario"].items()},
                }
            tests[test_name]["pr_auc"] = round(evaluate(scores, y_te, scenario, block)["pr_auc"], 4)
        booster.save_model(str(TIERS_DIR / f"{key}.txt"))
        out[key] = {k: v for k, v in tier.items() if k != "production"} | {
            "thresholds": {"block": block, "review": review}, "trees": booster.num_trees(), "test": tests}
        a = tests["adaptive"]["review"]
        print(f"{tier['name']:<8} trees {booster.num_trees():>4}  adaptive recall@review {a['recall']:.1%}  "
              f"PR-AUC {tests['adaptive']['pr_auc']:.3f}  rented recall@review "
              f"{_rented(tests['patched']['review']):.1%}")
    meta = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tiers": out}
    (TIERS_DIR / "tiers.json").write_text(json.dumps(meta, indent=1))
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "tiers.md").write_text(to_markdown(out), encoding="utf-8")
    return out


def _rented(level: dict) -> float:
    by = level["recall_by_strategy"]
    rented = [v for k, v in by.items() if k.endswith("/rented")]
    return sum(rented) / len(rented) if rented else 0.0


def to_markdown(out: dict) -> str:
    lines = [
        "# The four difficulty levels",
        "",
        "Generated by `python -m momofraud.tiers`. Each level is a separately trained LightGBM model.",
        "Thresholds: 90% precision to block, 50% to review, chosen on each model's own validation days.",
        "Recall is measured at the review threshold on the test days (75-89).",
        "",
        "| Level | Knows | PR-AUC (adaptive) | Recall (adaptive) | False alarms / 10k | Rented attacks caught |",
        "|---|---|---|---|---|---|",
    ]
    for tier in out.values():
        a, p = tier["test"]["adaptive"], tier["test"]["patched"]
        lines.append(f"| {tier['name']} | {tier['knows']} | {a['pr_auc']:.3f} | {a['review']['recall']:.0%} | "
                     f"{a['review']['false_alarms_per_10k']:.1f} | {_rented(p['review']):.0%} |")
    lines += ["", "Recall by scenario at the review threshold, adaptive world:", "",
              "| Level | " + " | ".join(sorted(next(iter(out.values()))["test"]["adaptive"]["review"]
                                            ["recall_by_scenario"])) + " |",
              "|---|---|---|---|"]
    for tier in out.values():
        by = tier["test"]["adaptive"]["review"]["recall_by_scenario"]
        lines.append(f"| {tier['name']} | " + " | ".join(f"{by[k]:.0%}" for k in sorted(by)) + " |")
    return "\n".join(lines) + "\n"


def copy_production() -> None:
    shutil.copy(MODEL_FILE, TIERS_DIR / "expert.txt")


if __name__ == "__main__":
    run()
