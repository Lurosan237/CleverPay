"""Compute and cache behavioural features for the simulated worlds.

    python -m momofraud.featurestore            # all worlds in data/simulated/
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from momofraud.behaviour import compute_features
from momofraud.paths import ROOT

SIM_DIR = ROOT / "data" / "simulated"
FEATURE_DIR = ROOT / "data" / "features"


def load_world(name: str) -> dict[str, pd.DataFrame]:
    folder = SIM_DIR / name
    return {part: pd.read_parquet(folder / f"{part}.parquet")
            for part in ("transactions", "account_events", "accounts")}


def features_for(name: str, refresh: bool = False) -> pd.DataFrame:
    path = FEATURE_DIR / f"{name}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    started = time.perf_counter()
    features = compute_features(load_world(name))
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    features.to_parquet(path)
    print(f"{name}: {len(features):,} rows of features in {time.perf_counter() - started:.0f}s -> {path}")
    return features


if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name for p in SIM_DIR.iterdir() if p.is_dir())
    for world in names:
        features_for(world, refresh=True)
