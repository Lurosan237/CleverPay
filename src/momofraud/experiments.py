"""Stage 3 experiments: do behavioural features catch what transaction-only models miss?

    python -m momofraud.featurestore      # once, after simulating the worlds
    python -m momofraud.experiments       # writes reports/behaviour.md and .json

Setup
- Three simulated worlds with the same legitimate traffic: naive fraudsters only,
  adaptive fraudsters only, and a 50/50 mix.
- Time split in every world: train on days 0-59, validate on 60-74, test on 75-89.
- The alert threshold is set on the training world's validation days for 90%
  precision and then used unchanged, as it would be in production.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from momofraud.behaviour import FEATURE_GROUPS, FEATURES
from momofraud.featurestore import SIM_DIR, features_for
from momofraud.metrics import summary, threshold_for_precision
from momofraud.paths import REPORTS_DIR

TRAIN_DAYS, VALIDATION_DAYS = (0, 60), (60, 75)  # test: day 75 onwards
TARGET_PRECISION = 0.90
SEED = 42
WORLDS = ("naive", "mixed", "adaptive")
SCENARIO_NAMES = {
    "account_takeover": "Account takeover",
    "withdrawal_request": "Withdrawal request",
    "wrong_transfer": "\"Sent by mistake\"",
}


@dataclass
class Dataset:
    """Features and labels of one world's transfers and withdrawals, split by time."""

    x: pd.DataFrame
    y: np.ndarray
    scenario: pd.Series   # "legit" or "<scenario>/<strategy>"
    part: np.ndarray      # "train" | "validation" | "test"
    day: np.ndarray | None = None  # day of the simulation, for monitoring over time

    def select(self, part: str) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
        mask = self.part == part
        return self.x[mask], self.y[mask], self.scenario[mask]


def load_dataset(name: str) -> Dataset:
    tx = pd.read_parquet(SIM_DIR / name / "transactions.parquet",
                         columns=["tx_id", "timestamp", "type", "status", "is_fraud", "scenario", "strategy",
                                  "role"])
    tx = tx[tx["type"].isin(["TRANSFER", "CASH_OUT"]) & (tx["status"] != "DECLINED")]
    # Decisions to make: legitimate transactions and money leaving a victim's account
    tx = tx[tx["is_fraud"].eq(0) | tx["role"].eq("victim_debit")].set_index("tx_id")
    x = features_for(name).loc[tx.index]
    day = (tx["timestamp"] - tx["timestamp"].min().normalize()).dt.days.to_numpy()
    part = np.where(day < TRAIN_DAYS[1], "train", np.where(day < VALIDATION_DAYS[1], "validation", "test"))
    scenario = tx["scenario"].astype(str) + "/" + tx["strategy"].astype(str)
    scenario = scenario.where(tx["is_fraud"] == 1, "legit")
    return Dataset(x=x, y=tx["is_fraud"].to_numpy(), scenario=scenario, part=part, day=day)


def adversarial_copies(data: Dataset, copies: int = 3, seed: int = SEED) -> tuple[pd.DataFrame, np.ndarray]:
    """Extra training examples: account takeovers as if the fraudster had used their phone on the
    account for 1-4 weeks before stealing, so the device would no longer look new or young.

    Only the device features change; everything else (the recent PIN reset or SIM swap, the new
    recipient, the share of the balance taken) stays as it was. The model has to learn to use
    those signals too. Validation and test data are never augmented.
    """
    rng = np.random.default_rng(seed)
    x_tr, _, scenario = data.select("train")
    takeovers = x_tr[scenario.str.startswith("account_takeover").to_numpy()]
    frames = []
    for _ in range(copies):
        n = len(takeovers)
        frames.append(takeovers.assign(
            device_new=0.0,
            device_history=np.log1p(rng.integers(5, 60, size=n)).astype(np.float32),
            hours_since_device_first_seen=rng.uniform(7 * 24, 28 * 24, size=n).astype(np.float32),
        ))
    extra = pd.concat(frames)
    return extra, np.ones(len(extra), dtype=int)


def train_lightgbm(data: Dataset, features: list[str],
                   extra: tuple[pd.DataFrame, np.ndarray] | None = None) -> lgb.LGBMClassifier:
    x_tr, y_tr, _ = data.select("train")
    if extra is not None:
        x_tr, y_tr = pd.concat([x_tr, extra[0]]), np.concatenate([y_tr, extra[1]])
    x_va, y_va, _ = data.select("validation")
    model = lgb.LGBMClassifier(
        n_estimators=3000, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8,
        subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=SEED, verbose=-1,
    )
    model.fit(x_tr[features], y_tr, eval_set=[(x_va[features], y_va)], eval_metric="average_precision",
              callbacks=[lgb.early_stopping(150, verbose=False)])
    return model


def evaluate(scores: np.ndarray, y: np.ndarray, scenario: pd.Series, threshold: float) -> dict:
    flagged = scores >= threshold
    by_scenario = {}
    for name in sorted(set(scenario) - {"legit"}):
        mask = (scenario == name).to_numpy()
        by_scenario[name] = {"caught": float(flagged[mask].mean()), "n": int(mask.sum())}
    legit = y == 0
    return {
        **summary(y, scores),
        "precision_at_threshold": float(y[flagged].mean()) if flagged.any() else 0.0,
        "recall_at_threshold": float(flagged[y == 1].mean()),
        "false_alarms_per_10k": float(flagged[legit].mean() * 10_000),
        "by_scenario": by_scenario,
    }


def run_experiment(train_world: Dataset, test_worlds: dict[str, Dataset], features: list[str],
                   model=None) -> dict:
    model = model or train_lightgbm(train_world, features)
    x_va, y_va, _ = train_world.select("validation")
    threshold = threshold_for_precision(y_va, model.predict_proba(x_va[features])[:, 1], TARGET_PRECISION)
    results = {"threshold": threshold, "best_iteration": int(getattr(model, "best_iteration_", 0) or 0)}
    for name, data in test_worlds.items():
        x_te, y_te, scenario = data.select("test")
        results[name] = evaluate(model.predict_proba(x_te[features])[:, 1], y_te, scenario, threshold)
    return results | {"_model": model}


def sensitivity(model, features: list[str], data: Dataset, threshold: float) -> dict[str, float]:
    """What would an adaptive account takeover have to do to get past the model?

    Takes the adaptive takeovers in the test period and edits their features as if the
    fraudster had done more to blend in, then re-scores them. Each change has a cost for
    the fraudster, noted in the report.
    """
    x_te, _, scenario = data.select("test")
    takeovers = x_te[(scenario == "account_takeover/adaptive").to_numpy()][features].copy()
    month = 24 * 30.0
    variants = {
        "As simulated": {},
        "Phone used on the account for a month first": {
            "hours_since_device_first_seen": month, "device_history": np.log1p(30)},
        "SIM swap / PIN reset a month earlier": {"hours_since_sim_swap_or_pin_reset": month},
        "Both of the above": {
            "hours_since_device_first_seen": month, "device_history": np.log1p(30),
            "hours_since_sim_swap_or_pin_reset": month},
        "Both, and money sent to the victim's usual contacts": {
            "hours_since_device_first_seen": month, "device_history": np.log1p(30),
            "hours_since_sim_swap_or_pin_reset": month, "recipient_new": 0.0, "pair_history": np.log1p(5)},
    }
    out = {}
    for label, changes in variants.items():
        variant = takeovers.assign(**changes)
        out[label] = float((model.predict_proba(variant)[:, 1] >= threshold).mean())
    return out


def run() -> dict:
    data = {name: load_dataset(name) for name in WORLDS}
    tests = {"naive": data["naive"], "adaptive": data["adaptive"]}
    transaction_only = FEATURE_GROUPS["transaction"]

    results: dict = {"experiments": {}}
    plan = {
        "Transaction only, trained on naive fraud": ("naive", transaction_only),
        "Behavioural, trained on naive fraud": ("naive", FEATURES),
        "Behavioural, trained on mixed fraud": ("mixed", FEATURES),
    }
    models = {}
    for label, (world, features) in plan.items():
        outcome = run_experiment(data[world], tests, features)
        models[label] = outcome.pop("_model")
        results["experiments"][label] = outcome
        print(f"{label}: adaptive-world recall {outcome['adaptive']['recall_at_threshold']:.1%}, "
              f"precision {outcome['adaptive']['precision_at_threshold']:.1%}")

    robust_label = "Behavioural, mixed fraud + adversarial copies"
    robust = train_lightgbm(data["mixed"], FEATURES, extra=adversarial_copies(data["mixed"]))
    outcome = run_experiment(data["mixed"], tests, FEATURES, model=robust)
    models[robust_label] = outcome.pop("_model")
    results["experiments"][robust_label] = outcome
    print(f"{robust_label}: adaptive-world recall {outcome['adaptive']['recall_at_threshold']:.1%}, "
          f"precision {outcome['adaptive']['precision_at_threshold']:.1%}")

    main_label = "Behavioural, trained on mixed fraud"
    main = models[main_label]
    gain = pd.Series(main.booster_.feature_importance("gain"), index=FEATURES)
    results["gain_importance"] = (gain / gain.sum()).sort_values(ascending=False).round(4).to_dict()

    # Ablation: retrain without each feature group (trained on mixed, tested on adaptive)
    results["ablation"] = {}
    for group, members in FEATURE_GROUPS.items():
        if group == "transaction":
            continue
        kept = [f for f in FEATURES if f not in members]
        outcome = run_experiment(data["mixed"], {"adaptive": data["adaptive"]}, kept)
        outcome.pop("_model")
        results["ablation"][group] = outcome["adaptive"]
        print(f"without {group}: adaptive recall {outcome['adaptive']['recall_at_threshold']:.1%}")

    results["sensitivity"] = {
        label: sensitivity(models[label], FEATURES, data["adaptive"],
                           results["experiments"][label]["threshold"])
        for label in (main_label, robust_label)
    }
    results["_models"] = models
    results["_data"] = data
    return results


# -- report ---------------------------------------------------------------------------------

def _pct(x: float) -> str:
    return f"{x:.0%}" if x >= 0.995 or x == 0 else f"{x:.1%}"


def scenario_rows(outcome: dict) -> dict[str, float]:
    """Per-scenario recall, both strategies combined (weighted by count)."""
    combined: dict[str, list[float]] = {}
    for name, v in outcome["by_scenario"].items():
        scenario = name.split("/")[0]
        caught, n = combined.get(scenario, [0.0, 0])
        combined[scenario] = [caught + v["caught"] * v["n"], n + v["n"]]
    return {s: c / n for s, (c, n) in combined.items()}


def to_markdown(r: dict) -> str:
    exp = r["experiments"]
    labels = list(exp)
    lines = [
        "# Stage 3: behavioural features",
        "",
        "Generated by `python -m momofraud.experiments`. Three simulated worlds with identical legitimate",
        "traffic: naive fraudsters only, adaptive fraudsters only, and a 50/50 mix. Models train on days",
        "0-59, the alert threshold is set for 90% precision on days 60-74 of the training world, and",
        "everything below is measured on days 75-89, never seen during training.",
        "",
        "## Share of victim transactions caught (adaptive world)",
        "",
        "| | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    rows = {label: scenario_rows(exp[label]["adaptive"]) for label in labels}
    for scenario, pretty in SCENARIO_NAMES.items():
        lines.append(f"| {pretty} | " + " | ".join(_pct(rows[lb].get(scenario, 0)) for lb in labels) + " |")
    lines += [
        "| **All victim transactions** | " + " | ".join(
            f"**{_pct(exp[lb]['adaptive']['recall_at_threshold'])}**" for lb in labels) + " |",
        "| Precision of alerts | " + " | ".join(
            _pct(exp[lb]["adaptive"]["precision_at_threshold"]) for lb in labels) + " |",
        "| False alarms per 10,000 legitimate | " + " | ".join(
            f"{exp[lb]['adaptive']['false_alarms_per_10k']:.1f}" for lb in labels) + " |",
        "| PR-AUC | " + " | ".join(f"{exp[lb]['adaptive']['pr_auc']:.3f}" for lb in labels) + " |",
        "",
        "## Same models on the naive world",
        "",
        "| | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    rows = {label: scenario_rows(exp[label]["naive"]) for label in labels}
    for scenario, pretty in SCENARIO_NAMES.items():
        lines.append(f"| {pretty} | " + " | ".join(_pct(rows[lb].get(scenario, 0)) for lb in labels) + " |")
    lines += [
        "| Precision of alerts | " + " | ".join(
            _pct(exp[lb]["naive"]["precision_at_threshold"]) for lb in labels) + " |",
        "| PR-AUC | " + " | ".join(f"{exp[lb]['naive']['pr_auc']:.3f}" for lb in labels) + " |",
        "",
        "## Which signals matter (ablation)",
        "",
        "The mixed-trained model retrained without one feature group at a time, tested on the adaptive",
        "world.",
        "",
        "| Without | " + " | ".join(SCENARIO_NAMES.values()) + " | All | PR-AUC |",
        "|---|" + "---|" * (len(SCENARIO_NAMES) + 2),
    ]
    full = exp["Behavioural, trained on mixed fraud"]["adaptive"]
    for group, outcome in [("(nothing removed)", full)] + list(r["ablation"].items()):
        per = scenario_rows(outcome)
        lines.append(f"| {group} | " + " | ".join(_pct(per.get(s, 0)) for s in SCENARIO_NAMES)
                     + f" | {_pct(outcome['recall_at_threshold'])} | {outcome['pr_auc']:.3f} |")
    top = list(r["gain_importance"].items())[:8]
    lines += [
        "",
        "Most important features of the mixed-trained model (share of total gain): "
        + ", ".join(f"`{k}` {v:.0%}" for k, v in top) + ".",
        "",
        "## What an adaptive takeover would have to do to get through",
        "",
        "Adaptive account takeovers from the test period, with their features edited as if the fraudster",
        "had done more to blend in, re-scored by the mixed-trained model:",
        "",
        "| Fraudster's extra effort | Mixed-trained model | With adversarial copies |",
        "|---|---|---|",
    ]
    plain, robust = r["sensitivity"].values()
    for label in plain:
        lines.append(f"| {label} | {_pct(plain[label])} | {_pct(robust[label])} |")
    return "\n".join(lines) + "\n"


def to_json(r: dict) -> str:
    return json.dumps({k: v for k, v in r.items() if not k.startswith("_")}, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    report = run()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "behaviour.json").write_text(to_json(report))
    (REPORTS_DIR / "behaviour.md").write_text(to_markdown(report), encoding="utf-8")
    print((REPORTS_DIR / "behaviour.md").read_text(encoding="utf-8"))
