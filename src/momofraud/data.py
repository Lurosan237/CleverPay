"""Load the PaySim dataset into a tidy, typed parquet file.

PaySim (Lopez-Rojas et al., 2016) is a simulator calibrated on one month of real
logs from a mobile money service in an African country. The Kaggle release has
~6.4 million transactions over 744 hourly steps (30 days).

Usage:
    python -m momofraud.data            # data/raw/*.zip -> data/processed/paysim.parquet
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from momofraud.paths import PROCESSED_DIR, RAW_DIR

# Original Kaggle column -> our name (snake_case, typo "Org" fixed)
COLUMNS = {
    "step": "step",
    "type": "type",
    "amount": "amount",
    "nameOrig": "orig_account",
    "oldbalanceOrg": "orig_balance_before",
    "newbalanceOrig": "orig_balance_after",
    "nameDest": "dest_account",
    "oldbalanceDest": "dest_balance_before",
    "newbalanceDest": "dest_balance_after",
    "isFraud": "is_fraud",
    "isFlaggedFraud": "is_flagged_by_rule",
}

TRANSACTION_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

READ_DTYPES = {
    "step": "int16",
    "type": "category",
    "amount": "float64",
    "nameOrig": "string[pyarrow]",
    "oldbalanceOrg": "float64",
    "newbalanceOrig": "float64",
    "nameDest": "string[pyarrow]",
    "oldbalanceDest": "float64",
    "newbalanceDest": "float64",
    "isFraud": "int8",
    "isFlaggedFraud": "int8",
}


def tidy(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename columns, set types and add time features. Works on any PaySim-shaped frame."""
    missing = set(COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"Not a PaySim file, missing columns: {sorted(missing)}")

    df = raw.rename(columns=COLUMNS)[list(COLUMNS.values())].copy()
    df["type"] = pd.Categorical(df["type"], categories=TRANSACTION_TYPES)
    if df["type"].isna().any():
        raise ValueError("Unknown transaction type in data")
    df["step"] = df["step"].astype("int16")
    df["is_fraud"] = df["is_fraud"].astype("int8")
    df["is_flagged_by_rule"] = df["is_flagged_by_rule"].astype("int8")
    # Merchant accounts start with "M"; PaySim does not record their balances
    df["dest_is_merchant"] = df["dest_account"].str.startswith("M").astype("int8")
    # One step = one hour of simulated time
    df["day"] = (df["step"] // 24).astype("int8")
    df["hour"] = (df["step"] % 24).astype("int8")
    return df


def find_raw_file(raw_dir: Path = RAW_DIR) -> Path:
    candidates = sorted([*raw_dir.glob("*.zip"), *raw_dir.glob("*.csv")])
    if not candidates:
        raise FileNotFoundError(
            f"No PaySim file in {raw_dir}. Download it from "
            "https://www.kaggle.com/datasets/ealaxi/paysim1 and put the zip there."
        )
    return candidates[0]


def read_raw(path: Path) -> pd.DataFrame:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            csv_names = [n for n in archive.namelist() if n.endswith(".csv")]
            if len(csv_names) != 1:
                raise ValueError(f"Expected one CSV in {path.name}, found {csv_names}")
            with archive.open(csv_names[0]) as handle:
                return pd.read_csv(handle, dtype=READ_DTYPES, engine="pyarrow")
    # The pyarrow engine is ~10x faster than the default parser on the 470 MB CSV
    return pd.read_csv(path, dtype=READ_DTYPES, engine="pyarrow")


def build(raw_dir: Path = RAW_DIR, out_dir: Path = PROCESSED_DIR) -> Path:
    source = find_raw_file(raw_dir)
    df = tidy(read_raw(source))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "paysim.parquet"
    df.to_parquet(out, index=False)
    print(f"{source.name}: {len(df):,} rows -> {out}")
    return out


def load(path: Path | None = None) -> pd.DataFrame:
    return pd.read_parquet(path or PROCESSED_DIR / "paysim.parquet")


if __name__ == "__main__":
    build()
