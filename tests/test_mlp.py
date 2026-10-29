import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from sklearn.metrics import average_precision_score  # noqa: E402

from momofraud.behaviour import FEATURES  # noqa: E402
from momofraud.mlp import TorchClassifier  # noqa: E402


def test_mlp_learns_a_simple_rule_and_returns_probabilities():
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(4000, len(FEATURES))).astype(np.float32), columns=FEATURES)
    y = (x["device_new"] + x["recipient_new"] > 2.0).to_numpy().astype(int)
    model = TorchClassifier(FEATURES, hidden=(16,)).fit(x[:3000], y[:3000], x[3000:], y[3000:], epochs=15,
                                                         batch_size=256)
    p = model.predict_proba(x[3000:])
    assert p.shape == (1000, 2)
    assert np.allclose(p.sum(axis=1), 1.0)
    # Up-weighting fraud shifts raw probabilities upward (thresholds are set on validation data),
    # so check ranking quality rather than probability values. Base rate here is about 8%.
    assert average_precision_score(y[3000:], p[:, 1]) > 0.6
