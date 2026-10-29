"""The exported model, scored one transaction at a time.

Explanations are exact SHAP values (TreeSHAP), which LightGBM computes natively with
`pred_contrib=True`: one contribution per feature, in log-odds, that add up exactly to
the model's raw score. No separate `shap` package is needed at serving time.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np

from momofraud.behaviour import FEATURES
from momofraud.paths import MODELS_DIR

DEFAULT_MODEL = MODELS_DIR / "fraud_lgbm.txt"
DEFAULT_METADATA = MODELS_DIR / "metadata.json"


@dataclass
class Explanation:
    probability: float
    raw_score: float          # log-odds
    bias: float               # the model's average log-odds (SHAP expected value)
    contributions: np.ndarray  # one per feature, log-odds; bias + sum == raw_score


class FraudModel:
    def __init__(self, model_file: Path = DEFAULT_MODEL, metadata_file: Path = DEFAULT_METADATA):
        self.booster = lgb.Booster(model_file=str(model_file))
        self.metadata = json.loads(Path(metadata_file).read_text())
        if self.metadata["features"] != FEATURES:
            raise ValueError("Model was trained on a different feature list: retrain with momofraud.train")
        self.block = float(self.metadata["thresholds"]["block"])
        self.review = float(self.metadata["thresholds"]["review"])

    def probability(self, features: list[float]) -> float:
        return float(self.booster.predict(np.asarray([features], dtype=np.float64))[0])

    def explain(self, features: list[float]) -> Explanation:
        row = np.asarray([features], dtype=np.float64)
        contrib = self.booster.predict(row, pred_contrib=True)[0]
        raw = float(contrib.sum())
        return Explanation(probability=1 / (1 + math.exp(-raw)), raw_score=raw, bias=float(contrib[-1]),
                           contributions=contrib[:-1])

    def decide(self, probability: float) -> str:
        if probability >= self.block:
            return "block"
        if probability >= self.review:
            return "review"
        return "approve"
