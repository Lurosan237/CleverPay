import numpy as np

from momofraud.data import tidy
from momofraud.features import FEATURE_SETS, HONEST_FEATURES, build_features, scored
from momofraud.metrics import recall_at_precision, summary, threshold_for_precision
from momofraud.split import SPLITS


def test_only_transfer_and_cash_out_are_scored(raw_sample):
    assert set(scored(tidy(raw_sample))["type"]) == {"TRANSFER", "CASH_OUT"}


def test_empties_account(raw_sample):
    x = build_features(tidy(raw_sample))
    assert x["empties_account"].tolist() == [0, 1, 1, 0, 0]


def test_honest_features_never_use_post_transaction_data():
    banned = ("after", "error", "hour")
    assert not [f for f in HONEST_FEATURES if any(word in f for word in banned)]


def test_ablation_hides_sender_balance():
    assert "empties_account" not in FEATURE_SETS["no_sender_balance"]


def test_amount_to_balance_handles_zero_balance(raw_sample):
    raw_sample.loc[0, "oldbalanceOrg"] = 0.0
    assert np.isfinite(build_features(tidy(raw_sample))["amount_to_balance"]).all()


def test_splits_are_ordered_and_disjoint():
    days = [list(r) for r in SPLITS.values()]
    flat = [d for part in days for d in part]
    assert flat == sorted(flat) and len(flat) == len(set(flat)) == 31


def test_metrics_on_perfect_and_random_scores():
    y = np.array([0] * 98 + [1] * 2)
    perfect = y.astype(float)
    assert summary(y, perfect)["pr_auc"] == 1.0
    assert recall_at_precision(y, perfect, 0.9) == 1.0
    assert threshold_for_precision(y, perfect, 0.9) == 1.0
    rng = np.random.default_rng(0)
    assert summary(y, rng.random(100))["pr_auc"] < 0.5
