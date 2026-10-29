"""PyTorch baseline: a small neural network on the same behavioural features.

    pip install torch
    python -m momofraud.mlp        # writes reports/mlp.md and .json

Trained on the mixed world like the main LightGBM model, with the same split, the
same threshold rule and the same test sets, so the two are directly comparable.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import torch
from torch import nn

from momofraud.behaviour import FEATURES
from momofraud.experiments import (
    SCENARIO_NAMES,
    _pct,
    load_dataset,
    run_experiment,
    scenario_rows,
    train_lightgbm,
)
from momofraud.metrics import summary
from momofraud.paths import REPORTS_DIR

SEED = 42


class TorchClassifier:
    """A standardising MLP with a scikit-learn-like predict_proba."""

    def __init__(self, features: list[str], hidden: tuple[int, ...] = (64, 32), dropout: float = 0.1):
        torch.manual_seed(SEED)
        layers: list[nn.Module] = []
        width = len(features)
        for size in hidden:
            layers += [nn.Linear(width, size), nn.ReLU(), nn.Dropout(dropout)]
            width = size
        layers.append(nn.Linear(width, 1))
        self.net = nn.Sequential(*layers)
        self.features = features
        self.mean = np.zeros(len(features), dtype=np.float32)
        self.std = np.ones(len(features), dtype=np.float32)
        self.best_epoch = 0

    def _tensor(self, x: pd.DataFrame) -> torch.Tensor:
        values = (x[self.features].to_numpy(dtype=np.float32) - self.mean) / self.std
        return torch.from_numpy(values)

    def fit(self, x: pd.DataFrame, y: np.ndarray, x_val: pd.DataFrame, y_val: np.ndarray,
            epochs: int = 40, batch_size: int = 4096, patience: int = 5) -> TorchClassifier:
        values = x[self.features].to_numpy(dtype=np.float32)
        self.mean = values.mean(axis=0)
        self.std = values.std(axis=0) + 1e-6
        inputs, targets = self._tensor(x), torch.from_numpy(y.astype(np.float32))
        # Fraud is ~1 in 1,000: weight it up, but not all the way (that makes scores noisy)
        pos_weight = torch.tensor(min((len(y) - y.sum()) / max(y.sum(), 1), 50.0))
        loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        optimiser = torch.optim.Adam(self.net.parameters(), lr=1e-3, weight_decay=1e-5)
        generator = torch.Generator().manual_seed(SEED)

        best_score, best_state, stale = -1.0, None, 0
        for epoch in range(epochs):
            self.net.train()
            order = torch.randperm(len(inputs), generator=generator)
            for start in range(0, len(order), batch_size):
                batch = order[start:start + batch_size]
                optimiser.zero_grad()
                loss = loss_fn(self.net(inputs[batch]).squeeze(1), targets[batch])
                loss.backward()
                optimiser.step()
            score = summary(y_val, self.predict_proba(x_val)[:, 1])["pr_auc"]
            if score > best_score:
                best_score, stale, self.best_epoch = score, 0, epoch + 1
                best_state = {k: v.clone() for k, v in self.net.state_dict().items()}
            else:
                stale += 1
                if stale >= patience:
                    break
        self.net.load_state_dict(best_state)
        return self

    @torch.no_grad()
    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        self.net.eval()
        p = torch.sigmoid(self.net(self._tensor(x)).squeeze(1)).numpy().astype(np.float64)
        return np.column_stack([1 - p, p])


def single_row_latency(model, x: pd.DataFrame, n: int = 2000) -> dict[str, float]:
    """Time to score one transaction at a time (what an API does), in microseconds."""
    rows = [x.iloc[[i]] for i in range(min(n, len(x)))]
    timings = []
    for row in rows:
        start = time.perf_counter()
        model.predict_proba(row)
        timings.append((time.perf_counter() - start) * 1e6)
    return {"p50_us": float(np.percentile(timings, 50)), "p95_us": float(np.percentile(timings, 95))}


def run() -> dict:
    torch.set_num_threads(2)
    mixed, naive, adaptive = (load_dataset(n) for n in ("mixed", "naive", "adaptive"))
    tests = {"naive": naive, "adaptive": adaptive}
    results = {}

    x_tr, y_tr, _ = mixed.select("train")
    x_va, y_va, _ = mixed.select("validation")
    started = time.perf_counter()
    mlp = TorchClassifier(FEATURES).fit(x_tr, y_tr, x_va, y_va)
    mlp_seconds = time.perf_counter() - started

    started = time.perf_counter()
    gbm = train_lightgbm(mixed, FEATURES)
    gbm_seconds = time.perf_counter() - started

    x_te, _, _ = adaptive.select("test")
    for label, model, seconds in (("LightGBM", gbm, gbm_seconds), ("PyTorch MLP", mlp, mlp_seconds)):
        outcome = run_experiment(mixed, tests, FEATURES, model=model)
        outcome.pop("_model")
        outcome["train_seconds"] = round(seconds, 1)
        outcome["latency"] = single_row_latency(model, x_te)
        results[label] = outcome
        print(f"{label}: adaptive PR-AUC {outcome['adaptive']['pr_auc']:.3f}, "
              f"recall {outcome['adaptive']['recall_at_threshold']:.1%}, trained in {seconds:.0f}s")
    results["PyTorch MLP"]["best_epoch"] = mlp.best_epoch
    return results


def to_markdown(r: dict) -> str:
    labels = list(r)
    lines = [
        "# PyTorch baseline",
        "",
        "Generated by `python -m momofraud.mlp`. Both models use the same behavioural features, are",
        "trained on the mixed world (days 0-59), get their alert threshold for 90% precision on days",
        "60-74, and are tested on days 75-89 of the adaptive world.",
        "",
        "| | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    per = {lb: scenario_rows(r[lb]["adaptive"]) for lb in labels}
    for scenario, pretty in SCENARIO_NAMES.items():
        lines.append(f"| {pretty} | " + " | ".join(_pct(per[lb].get(scenario, 0)) for lb in labels) + " |")
    lines += [
        "| All victim transactions | "
        + " | ".join(_pct(r[lb]["adaptive"]["recall_at_threshold"]) for lb in labels) + " |",
        "| Precision of alerts | "
        + " | ".join(_pct(r[lb]["adaptive"]["precision_at_threshold"]) for lb in labels) + " |",
        "| PR-AUC | " + " | ".join(f"{r[lb]['adaptive']['pr_auc']:.3f}" for lb in labels) + " |",
        "| Training time | " + " | ".join(f"{r[lb]['train_seconds']:.0f} s" for lb in labels) + " |",
        "| Scoring one transaction, p50 / p95 | " + " | ".join(
            f"{r[lb]['latency']['p50_us']:.0f} / {r[lb]['latency']['p95_us']:.0f} µs"
            for lb in labels) + " |",
        "",
        "Latency is for the model alone, scoring one transaction at a time on a 2-core machine. The",
        "full API latency (feature lookup, HTTP, explanations) is measured in stage 4.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    report = run()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "mlp.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (REPORTS_DIR / "mlp.md").write_text(to_markdown(report), encoding="utf-8")
    print((REPORTS_DIR / "mlp.md").read_text(encoding="utf-8"))
