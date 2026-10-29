import pandas as pd
import pytest

from momofraud.data import read_raw, tidy


def test_tidy_renames_and_types(raw_sample):
    df = tidy(raw_sample)
    assert list(df.columns[:4]) == ["step", "type", "amount", "orig_account"]
    assert str(df["type"].dtype) == "category"
    assert df["is_fraud"].tolist() == [0, 1, 1, 0, 0]


def test_time_features(raw_sample):
    df = tidy(raw_sample)
    assert df.loc[4, "day"] == 1 and df.loc[4, "hour"] == 1  # step 25 = day 1, 01:00


def test_merchant_flag(raw_sample):
    assert tidy(raw_sample)["dest_is_merchant"].tolist() == [1, 0, 0, 0, 0]


def test_rejects_unknown_type(raw_sample):
    raw_sample.loc[0, "type"] = "AIRTIME"
    with pytest.raises(ValueError, match="Unknown transaction type"):
        tidy(raw_sample)


def test_rejects_other_files():
    with pytest.raises(ValueError, match="Not a PaySim file"):
        tidy(pd.DataFrame({"a": [1]}))


def test_reads_zipped_csv(tmp_path, raw_sample):
    path = tmp_path / "paysim.zip"
    raw_sample.to_csv(path, index=False, compression={"method": "zip", "archive_name": "log.csv"})
    assert len(tidy(read_raw(path))) == 5
