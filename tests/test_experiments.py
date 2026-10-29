import numpy as np
import pandas as pd
import pytest

from momofraud.behaviour import FEATURES
from momofraud.experiments import Dataset, adversarial_copies, evaluate, scenario_rows

DEVICE_FEATURES = {"device_new", "device_history", "hours_since_device_first_seen"}


def dataset() -> Dataset:
    rng = np.random.default_rng(0)
    n = 40
    x = pd.DataFrame(rng.random((n, len(FEATURES))).astype(np.float32), columns=FEATURES)
    scenario = pd.Series(["legit"] * 30 + ["account_takeover/adaptive"] * 6 + ["wrong_transfer/naive"] * 4)
    part = np.array(["train"] * 20 + ["validation"] * 10 + ["train"] * 10)
    return Dataset(x=x, y=(scenario != "legit").to_numpy().astype(int), scenario=scenario, part=part)


def test_adversarial_copies_only_touch_device_features_of_takeovers():
    data = dataset()
    extra, labels = adversarial_copies(data, copies=2)
    takeovers = data.x[(data.scenario == "account_takeover/adaptive").to_numpy()]
    assert len(extra) == 2 * len(takeovers) and (labels == 1).all()
    unchanged = [f for f in FEATURES if f not in DEVICE_FEATURES]
    original = pd.concat([takeovers, takeovers])[unchanged].to_numpy()
    np.testing.assert_array_equal(extra[unchanged].to_numpy(), original)
    assert (extra["device_new"] == 0).all()
    assert (extra["hours_since_device_first_seen"] >= 7 * 24).all()


def test_adversarial_copies_never_use_validation_rows():
    data = dataset()
    data.part[30:36] = "validation"  # move the takeovers out of training
    extra, _ = adversarial_copies(data)
    assert len(extra) == 0


def test_evaluate_and_per_scenario_recall():
    y = np.array([0, 0, 0, 1, 1, 1])
    scenario = pd.Series(["legit"] * 3 + ["a/naive", "a/adaptive", "b/naive"])
    scores = np.array([0.1, 0.2, 0.9, 0.8, 0.1, 0.95])
    out = evaluate(scores, y, scenario, threshold=0.5)
    assert out["recall_at_threshold"] == 2 / 3
    assert out["precision_at_threshold"] == 2 / 3
    assert out["false_alarms_per_10k"] == pytest.approx(10_000 / 3)
    assert scenario_rows(out) == {"a": 0.5, "b": 1.0}
