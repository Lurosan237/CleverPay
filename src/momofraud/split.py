"""Time-based train/validation/test split.

PaySim's legitimate traffic is dense on days 0-16 and sparse afterwards (the
simulator keeps injecting fraud at a constant rate, so the fraud rate jumps from
~0.15% to several percent). We train and evaluate on the dense period, where the
fraud rate is realistic, and keep the sparse tail as a separate stress test.
Splitting by time (never randomly) means the model is always tested on transactions
that happen *after* the ones it learned from, as it would be in production.
"""

from __future__ import annotations

import pandas as pd

SPLITS = {
    "train": range(0, 12),      # days 0-11
    "validation": range(12, 14),  # days 12-13: early stopping and threshold choice
    "test": range(14, 17),      # days 14-16: reported once, at the end
    "sparse_tail": range(17, 31),  # days 17-30: different base rate, stress test only
}


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {name: df[df["day"].isin(days)] for name, days in SPLITS.items()}
