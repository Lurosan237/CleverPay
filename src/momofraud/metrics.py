"""Metrics for rare-event detection. Accuracy is meaningless at a 0.15% fraud rate:
a model that never flags anything is 99.85% accurate."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve


def recall_at_precision(y_true, scores, min_precision: float) -> float:
    precision, recall, _ = precision_recall_curve(y_true, scores)
    ok = precision >= min_precision
    return float(recall[ok].max()) if ok.any() else 0.0


def precision_at_recall(y_true, scores, min_recall: float) -> float:
    precision, recall, _ = precision_recall_curve(y_true, scores)
    ok = recall >= min_recall
    return float(precision[ok].max()) if ok.any() else 0.0


def threshold_for_precision(y_true, scores, min_precision: float) -> float:
    """Lowest score threshold whose precision is at least min_precision (chosen on validation)."""
    precision, _, thresholds = precision_recall_curve(y_true, scores)
    ok = np.where(precision[:-1] >= min_precision)[0]
    return float(thresholds[ok[0]]) if len(ok) else 1.0


def summary(y_true, scores) -> dict[str, float]:
    return {
        "pr_auc": float(average_precision_score(y_true, scores)),
        "recall_at_p90": recall_at_precision(y_true, scores, 0.90),
        "recall_at_p50": recall_at_precision(y_true, scores, 0.50),
        "precision_at_r80": precision_at_recall(y_true, scores, 0.80),
        "fraud_rate": float(np.mean(y_true)),
        "n": int(len(y_true)),
        "n_fraud": int(np.sum(y_true)),
    }
