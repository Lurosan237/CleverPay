"""Train the production model and export it for the API.

    python -m momofraud.train        # writes models/fraud_lgbm.txt, metadata.json, drift_reference.json

The model is the stage 3 winner: LightGBM on all behavioural features, trained on the
mixed world (naive and adaptive fraud) plus adversarial copies of account takeovers
with an established phone. Two alert thresholds are chosen on the validation days:

- block:  90% precision. The transaction is stopped.
- review: 50% precision. The transaction goes through extra checks (in a real system, a
          confirmation call or a one-time code) before it is approved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import lightgbm as lgb

from momofraud.behaviour import FEATURES
from momofraud.experiments import adversarial_copies, evaluate, load_dataset, scenario_rows, train_lightgbm
from momofraud.metrics import threshold_for_precision
from momofraud.paths import MODELS_DIR

MODEL_FILE = MODELS_DIR / "fraud_lgbm.txt"
METADATA_FILE = MODELS_DIR / "metadata.json"
BLOCK_PRECISION, REVIEW_PRECISION = 0.90, 0.50


def main() -> None:
    mixed, adaptive = load_dataset("mixed"), load_dataset("adaptive")
    model = train_lightgbm(mixed, FEATURES, extra=adversarial_copies(mixed))

    x_va, y_va, _ = mixed.select("validation")
    val_scores = model.predict_proba(x_va[FEATURES])[:, 1]
    block = threshold_for_precision(y_va, val_scores, BLOCK_PRECISION)
    review = min(threshold_for_precision(y_va, val_scores, REVIEW_PRECISION), block)

    x_te, y_te, scenario = adaptive.select("test")
    test_scores = model.predict_proba(x_te[FEATURES])[:, 1]
    test = {name: evaluate(test_scores, y_te, scenario, threshold)
            for name, threshold in (("block", block), ("review", review))}

    MODELS_DIR.mkdir(exist_ok=True)
    model.booster_.save_model(str(MODEL_FILE))
    metadata = {
        "model": "LightGBM, behavioural features, trained on the mixed world + adversarial copies",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lightgbm_version": lgb.__version__,
        "features": FEATURES,
        "best_iteration": int(model.best_iteration_),
        "thresholds": {"block": block, "review": review},
        "threshold_rule": {"block": f"{BLOCK_PRECISION:.0%} precision on validation days 60-74",
                           "review": f"{REVIEW_PRECISION:.0%} precision on validation days 60-74"},
        "test_adaptive_world": {
            name: {
                "precision": round(r["precision_at_threshold"], 4),
                "recall": round(r["recall_at_threshold"], 4),
                "false_alarms_per_10k": round(r["false_alarms_per_10k"], 2),
                "recall_by_scenario": {k: round(v, 4) for k, v in scenario_rows(r).items()},
            }
            for name, r in test.items()
        },
    }
    METADATA_FILE.write_text(json.dumps(metadata, indent=2))
    # The drift reference must describe what this model was tuned on: rebuild it with the model
    from momofraud.monitoring import build_reference
    build_reference().save()
    print(json.dumps(metadata["thresholds"]), json.dumps(metadata["test_adaptive_world"], indent=2))


if __name__ == "__main__":
    main()
