"""Train and compare baseline models; writes reports/baselines.json and .md.

    python -m momofraud.baselines
"""

from __future__ import annotations

import json
import time

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from momofraud import data
from momofraud.features import FEATURE_SETS, build_features, scored
from momofraud.metrics import summary, threshold_for_precision
from momofraud.paths import REPORTS_DIR
from momofraud.split import split

SEED = 42


def lightgbm_model(class_weight: str | None):
    return lgb.LGBMClassifier(
        n_estimators=2000,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        class_weight=class_weight,
        random_state=SEED,
        verbose=-1,
    )


def fit_lightgbm(model, x_train, y_train, x_val, y_val):
    model.fit(
        x_train, y_train,
        eval_set=[(x_val, y_val)],
        eval_metric="average_precision",
        callbacks=[lgb.early_stopping(100, verbose=False)],
    )
    return model


EVASION_SHARES = (1.0, 0.95, 0.9, 0.7, 0.5)


def evasion_test(model, cols, validation: pd.DataFrame, test: pd.DataFrame) -> dict[str, float]:
    """Replay the test set's frauds as if each fraudster took only part of the balance.

    The alert threshold is fixed on the validation set (90% precision), as it would
    be in production. Returns the share of frauds still caught for each share taken.
    """
    threshold = threshold_for_precision(
        validation["is_fraud"], model.predict_proba(build_features(validation)[cols])[:, 1], 0.90
    )
    frauds = test[test["is_fraud"] == 1]
    caught = {}
    for share in EVASION_SHARES:
        variant = frauds.assign(amount=(frauds["orig_balance_before"] * share).round(2))
        scores = model.predict_proba(build_features(variant)[cols])[:, 1]
        caught[f"{share:.0%}"] = float(np.mean(scores >= threshold))
    return caught


def run() -> dict:
    df = scored(data.load())
    parts = {name: (build_features(part), part["is_fraud"].to_numpy()) for name, part in split(df).items()}
    x_tr, y_tr = parts["train"]
    x_va, y_va = parts["validation"]

    experiments = {
        "Rule: transaction empties the sender's account": ("rule", "honest", None),
        "Logistic regression (honest features)": ("logreg", "honest", None),
        "LightGBM (honest features)": ("lgbm", "honest", None),
        "LightGBM, class-weighted (honest features)": ("lgbm", "honest", "balanced"),
        "LightGBM (leaky features, for comparison)": ("lgbm", "leaky", None),
        "LightGBM without the sender's balance": ("lgbm", "no_sender_balance", None),
    }
    results = {}
    for name, (kind, feature_set, weight) in experiments.items():
        cols = FEATURE_SETS[feature_set]
        start = time.perf_counter()
        if kind == "rule":
            results[name] = {
                "features": "empties_account",
                **{part: summary(y, x["empties_account"].to_numpy() + 1e-9 * x["log_amount"].to_numpy())
                   for part, (x, y) in parts.items() if part != "train"},
            }
            print(f"{name}: test PR-AUC {results[name]['test']['pr_auc']:.3f}")
            continue
        if kind == "logreg":
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
            model.fit(x_tr[cols], y_tr)
            extra = {}
        else:
            model = fit_lightgbm(lightgbm_model(weight), x_tr[cols], y_tr, x_va[cols], y_va)
            extra = {"best_iteration": int(model.best_iteration_)}
        seconds = time.perf_counter() - start
        scores = {
            part: summary(y, model.predict_proba(x[cols])[:, 1])
            for part, (x, y) in parts.items() if part != "train"
        }
        results[name] = {"features": feature_set, "train_seconds": round(seconds, 1), **extra, **scores}
        print(f"{name}: test PR-AUC {scores['test']['pr_auc']:.3f}, "
              f"recall@P90 {scores['test']['recall_at_p90']:.3f} ({seconds:.0f}s)")
        if name == "LightGBM (honest features)":
            results[name]["evasion_caught"] = evasion_test(
                model, cols, split(df)["validation"], split(df)["test"]
            )
            importance = pd.Series(model.booster_.feature_importance("gain"), index=cols)
            results[name]["gain_importance"] = (importance / importance.sum()).round(3).sort_values(
                ascending=False).to_dict()
    return results


def to_markdown(results: dict) -> str:
    lines = [
        "# Baseline results",
        "",
        "Time-based split: train on days 0-11, validate on 12-13, **test on 14-16**.",
        "Only TRANSFER and CASH_OUT transactions (the only types with fraud).",
        "",
        "| Model | Test PR-AUC | Recall @ 90% precision | Precision @ 80% recall | Sparse-tail PR-AUC |",
        "|---|---|---|---|---|",
    ]
    for name, r in results.items():
        t, s = r["test"], r["sparse_tail"]
        lines.append(f"| {name} | {t['pr_auc']:.3f} | {t['recall_at_p90']:.1%} | "
                     f"{t['precision_at_r80']:.1%} | {s['pr_auc']:.3f} |")
    any_result = next(iter(results.values()))
    evasion = results["LightGBM (honest features)"]["evasion_caught"]
    lines += [
        "",
        "## Evasion test",
        "",
        "The test set's frauds replayed as if each fraudster took only part of the victim's balance,",
        "scored by the honest LightGBM with its alert threshold fixed on validation (90% precision):",
        "",
        "| Share of balance taken | " + " | ".join(evasion) + " |",
        "|---|" + "---|" * len(evasion),
        "| Frauds caught | " + " | ".join(f"{v:.1%}" for v in evasion.values()) + " |",
    ]
    lines += [
        "",
        "## What this shows",
        "",
        "- PaySim's simulated fraudsters almost always **take the whole balance**. The one-line rule",
        "  above matches the machine-learning models, so a near-perfect score on PaySim mostly means",
        "  the model found that rule.",
        "- Without the sender's balance the best model drops to the last row's PR-AUC: the remaining",
        "  signal is weak.",
        "- The evasion test makes it concrete: leaving even 5% of the balance behind is enough to",
        "  avoid almost every alert. That gap is what the game in this project is built to expose,",
        "  and what the adversarial training stage has to close.",
    ]
    t = any_result["test"]
    lines += ["", f"Test set: {t['n']:,} transactions, {t['n_fraud']} fraudulent ({t['fraud_rate']:.2%})."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    results = run()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "baselines.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    (REPORTS_DIR / "baselines.md").write_text(to_markdown(results), encoding="utf-8")
    print((REPORTS_DIR / "baselines.md").read_text(encoding="utf-8"))
