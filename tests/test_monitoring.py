import copy

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from momofraud.behaviour import FEATURES
from momofraud.monitoring import DriftMonitor, Reference, bin_edges, level, proportions, psi
from momofraud.serving.api import create_app
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network
from momofraud.sim.config import SimConfig
from momofraud.sim.engine import simulate

RNG = np.random.default_rng(0)


def fake_traffic(n: int, shift: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    x = RNG.normal(size=(n, len(FEATURES)))
    x[:, 0] = RNG.random(n) < 0.1          # a binary feature
    x[:, 1] += shift
    scores = 1 / (1 + np.exp(-(x[:, 1] - 6)))
    return x, scores


def test_psi_basics():
    a = np.array([0.25, 0.25, 0.5])
    assert psi(a, a) == 0
    assert psi(a, np.array([0.5, 0.25, 0.25])) > 0.25
    assert (level(0.05), level(0.15), level(0.4)) == ("stable", "watch", "drift")


def test_binary_feature_gets_two_bins():
    values = np.array([0, 0, 0, 1, 0, 1, 0, 0, 0, 0], dtype=float)
    edges = bin_edges(values)
    assert len(edges) <= 2
    assert proportions(values, edges).sum() == pytest.approx(1)
    assert proportions(values, edges)[0] == pytest.approx(0.8)


def test_same_traffic_is_stable_and_shifted_traffic_is_flagged():
    ref = Reference.build(*fake_traffic(20_000), review=0.01, block=0.1, source="test")
    same = ref.compare(*fake_traffic(5_000), review=0.01, block=0.1)
    assert same["status"] == "stable"
    moved = ref.compare(*fake_traffic(5_000, shift=1.0), review=0.01, block=0.1)
    assert moved["status"] == "drift"
    assert moved["top_features"][0]["feature"] == FEATURES[1]
    assert moved["score_psi"] > 0.25
    assert moved["review_rate"] > same["review_rate"]


def test_reference_round_trip(tmp_path):
    ref = Reference.build(*fake_traffic(2_000), review=0.01, block=0.1, source="test")
    ref.save(tmp_path / "ref.json")
    again = Reference.load(tmp_path / "ref.json")
    assert again.features == ref.features and again.review_rate == ref.review_rate


def test_live_monitor_warms_up_then_reports():
    ref = Reference.build(*fake_traffic(5_000), review=0.01, block=0.1, source="test")
    monitor = DriftMonitor(ref, review=0.01, block=0.1, window=300, min_rows=100)
    x, scores = fake_traffic(400)
    for row, score in zip(x[:50], scores[:50], strict=True):
        monitor.update(row.tolist(), float(score))
    assert monitor.report()["status"] == "warming_up"
    for row, score in zip(x[50:], scores[50:], strict=True):
        monitor.update(row.tolist(), float(score))
    report = monitor.report()
    assert report["rows_in_window"] == 300 and report["scored_since_start"] == 400
    assert report["status"] in ("stable", "watch")


def test_monitoring_endpoint_sees_api_traffic():
    network = Network.demo(users=600, days=10, seed=3)
    with TestClient(create_app(network=copy.deepcopy(network), model=FraudModel(), game_log=None)) as client:
        monitor = client.app.state.monitor
        assert monitor is not None, "models/drift_reference.json should be in the repo"
        assert client.get("/v1/monitoring").json()["status"] == "warming_up"
        monitor.min_rows = 3
        net = client.app.state.network
        pairs = [(s, r) for (s, r), n in net.state.pair_count.items()
                 if net.kind.get(s) == net.kind.get(r) == "customer"][:5]
        for s, r in pairs:
            client.post("/v1/transactions", json={"type": "TRANSFER", "sender": s, "receiver": r, "amount": 500,
                                                  "device": net.device.get(s)})
        client.post("/v1/score", json={"type": "TRANSFER", "sender": pairs[0][0], "receiver": pairs[0][1],
                                       "amount": 500})   # not committed: not counted
        report = client.get("/v1/monitoring").json()
        assert report["scored_since_start"] == len(pairs)
        assert report["status"] in ("stable", "watch", "drift")
        assert set(report["feature_psi"]) == set(FEATURES)


def test_phone_promotion_changes_nothing_before_it_starts():
    base = dict(n_users=400, days=13, seed=5)       # the promotion week fits: days 5-11
    plain = simulate(SimConfig(**base))
    promo = simulate(SimConfig(**base, promo_start_day=5, promo_new_phone_share=0.3))
    cutoff = pd.Timestamp(SimConfig.start) + pd.Timedelta(days=5)
    before = [f["transactions"][f["transactions"]["timestamp"] < cutoff].reset_index(drop=True) for f in (plain, promo)]
    before = [b.astype({c: str for c in b.select_dtypes("category").columns}) for b in before]
    pd.testing.assert_frame_equal(*before)
    changes = [(f["account_events"]["event"] == "DEVICE_CHANGE").sum() for f in (plain, promo)]
    assert changes[1] - changes[0] >= 0.3 * 400 * 0.8   # about 30% of the customers (most users are)


def test_rare_event_jump_is_caught_even_when_psi_is_small():
    x, scores = fake_traffic(50_000)
    x[:, 0] = RNG.random(len(x)) < 0.001                  # e.g. a new phone: 0.1% of transactions
    ref = Reference.build(x, scores, review=0.01, block=0.1, source="test")
    now, now_scores = fake_traffic(10_000)
    now[:, 0] = RNG.random(len(now)) < 0.02               # ... suddenly 2%
    result = ref.compare(now, now_scores, review=0.01, block=0.1)
    assert result["feature_psi"][FEATURES[0]] < 0.25      # PSI alone would not call it drift
    assert result["status"] == "drift"
    assert result["rate_jumps"][0]["feature"] == FEATURES[0]


def test_growing_counters_do_not_raise_the_status():
    x, scores = fake_traffic(20_000)
    ref = Reference.build(x, scores, review=0.01, block=0.1, source="test")
    now, now_scores = fake_traffic(5_000)
    i = FEATURES.index("sender_history")
    now[:, i] += 3                                        # every account is older now
    result = ref.compare(now, now_scores, review=0.01, block=0.1)
    assert result["growing_features"]["sender_history"] > 0.25
    assert result["status"] == "stable"
