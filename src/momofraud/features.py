"""Features for scoring a transaction *before* it is approved.

Feature policy (see reports/baselines.md for the evidence):

- Only information available at authorisation time: the type, the amount and the
  balances *before* the transaction. "Balance after" columns are excluded: they are
  computed after approval, and in PaySim 90% of legitimate transactions have
  balances that don't add up while fraudulent ones almost always do, so they leak
  the label through a simulator bookkeeping artifact.
- No time of day: PaySim injects fraud at a constant ~11 per hour regardless of
  traffic, so at 4 a.m. more than half of transactions are fraud. A model that
  learns "night = fraud" scores well here and would be useless on real traffic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Fraud only ever occurs in these two types; other types are scored as legitimate.
SCORED_TYPES = ("TRANSFER", "CASH_OUT")

HONEST_FEATURES = [
    "is_transfer",
    "log_amount",
    "log_orig_balance_before",
    "log_dest_balance_before",
    "amount_to_balance",
    "empties_account",
    "dest_empty_before",
    "amount_is_round",
]

# Deliberately leaky: used only to show how much "too good to be true" scores rely on artifacts
LEAKY_FEATURES = HONEST_FEATURES + [
    "hour",
    "orig_balance_error",
    "dest_balance_error",
    "log_orig_balance_after",
    "log_dest_balance_after",
]

# Ablation: what is left once the model cannot see how much the transaction drains the account
NO_SENDER_BALANCE_FEATURES = [
    f for f in HONEST_FEATURES
    if f not in ("log_orig_balance_before", "amount_to_balance", "empties_account")
]

FEATURE_SETS = {
    "honest": HONEST_FEATURES,
    "leaky": LEAKY_FEATURES,
    "no_sender_balance": NO_SENDER_BALANCE_FEATURES,
}


def scored(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the transaction types a model needs to score."""
    return df[df["type"].isin(SCORED_TYPES)]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    amount = df["amount"].astype("float64")
    orig_before = df["orig_balance_before"].astype("float64")
    dest_before = df["dest_balance_before"].astype("float64")

    out = pd.DataFrame(index=df.index)
    out["is_transfer"] = (df["type"] == "TRANSFER").astype("int8")
    out["log_amount"] = np.log1p(amount)
    out["log_orig_balance_before"] = np.log1p(orig_before)
    out["log_dest_balance_before"] = np.log1p(dest_before)
    # How much of the sender's balance this transaction moves (capped: some balances are 0)
    out["amount_to_balance"] = np.minimum(amount / np.maximum(orig_before, 1.0), 10.0)
    out["empties_account"] = (np.isclose(amount, orig_before) & (orig_before > 0)).astype("int8")
    out["dest_empty_before"] = (dest_before == 0).astype("int8")
    out["amount_is_round"] = (np.mod(amount, 1000) == 0).astype("int8")

    # Leaky extras (post-transaction information and simulator artifacts)
    out["hour"] = df["hour"].astype("int8")
    out["orig_balance_error"] = orig_before - amount - df["orig_balance_after"]
    out["dest_balance_error"] = dest_before + amount - df["dest_balance_after"]
    out["log_orig_balance_after"] = np.log1p(df["orig_balance_after"].astype("float64"))
    out["log_dest_balance_after"] = np.log1p(df["dest_balance_after"].astype("float64"))
    return out
