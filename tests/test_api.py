import copy
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from momofraud.serving.api import create_app
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network
from momofraud.sim.config import TRANSFER_TAX


@pytest.fixture(scope="module")
def base_network():
    return Network.demo(users=600, days=10, seed=3)


@pytest.fixture(scope="module")
def model():
    return FraudModel()


@pytest.fixture
def client(base_network, model):
    """A fresh copy of the network for every test, so tests can't affect each other."""
    with TestClient(create_app(network=copy.deepcopy(base_network), model=model)) as c:
        yield c


def regular_pair(client):
    """A customer and someone they have paid several times, with enough money."""
    net = client.app.state.network
    for (s, r), n in net.state.pair_count.items():
        if n >= 3 and net.kind.get(s) == net.kind.get(r) == "customer" and net.balance.get(s, 0) > 20_000:
            return s, r, net.device[s]
    raise AssertionError("no regular pair in the demo network")


def test_health_and_model(client):
    assert client.get("/health").json()["status"] == "ok"
    info = client.get("/v1/model").json()
    assert 0 < info["thresholds"]["review"] <= info["thresholds"]["block"] < 1


def test_regular_payment_is_approved_and_money_moves(client):
    s, r, device = regular_pair(client)
    before = client.get(f"/v1/accounts/{s}").json()["balance"]
    out = client.post("/v1/transactions", json={
        "type": "TRANSFER", "sender": s, "receiver": r, "amount": 5000, "device": device}).json()
    assert out["decision"] == "approve" and out["status"] == "SUCCESS"
    assert out["reasons"] == []  # approvals are not explained unless asked
    assert out["sender_balance"] == pytest.approx(before - 5000 - math.ceil(5000 * TRANSFER_TAX))


def test_naive_takeover_is_blocked_with_readable_reasons(client):
    s, _, _ = regular_pair(client)
    mule = client.post("/v1/accounts", json={"region": "Douala"}).json()["account"]
    client.post("/v1/events", json={"account": s, "event": "SIM_SWAP", "device": "D-fraudster"})
    balance = client.get(f"/v1/accounts/{s}").json()["balance"]
    out = client.post("/v1/transactions", json={
        "type": "TRANSFER", "sender": s, "receiver": mule, "amount": math.floor(balance / 1.002),
        "device": "D-fraudster"}).json()
    assert out["decision"] == "block" and out["status"] == "BLOCKED"
    assert out["sender_balance"] == balance  # nothing moved
    texts = " ".join(r["text"] for r in out["reasons"])
    assert "SIM swap" in texts or "phone" in texts
    assert out["reasons"] == sorted(out["reasons"], key=lambda r: -r["contribution"])


def test_reasons_in_french(client):
    s, _, _ = regular_pair(client)
    mule = client.post("/v1/accounts", json={}).json()["account"]
    client.post("/v1/events", json={"account": s, "event": "PIN_RESET", "device": "D-x"})
    out = client.post("/v1/score", json={"type": "TRANSFER", "sender": s, "receiver": mule, "amount": 20_000,
                                         "device": "D-x", "lang": "fr"}).json()
    assert out["reasons"] and any(w in out["reasons"][0]["text"] for w in ("Code PIN", "téléphone", "Compte"))


def test_shap_values_add_up_to_the_score(client, model):
    s, r, device = regular_pair(client)
    net = client.app.state.network
    record = net.build("TRANSFER", "USSD", s, r, 7000, "D-new", net.now + 1)
    features = net.state.features(record)
    explanation = model.explain(features)
    assert explanation.bias + explanation.contributions.sum() == pytest.approx(explanation.raw_score)
    assert explanation.probability == pytest.approx(model.probability(features), rel=1e-6)


def test_score_endpoint_changes_nothing(client):
    s, r, device = regular_pair(client)
    body = {"type": "TRANSFER", "sender": s, "receiver": r, "amount": 3000, "device": device, "explain": True}
    first, second = client.post("/v1/score", json=body).json(), client.post("/v1/score", json=body).json()
    assert first["status"] == "NOT_COMMITTED" and first["transaction_id"] is None
    assert first["score"] == second["score"]
    assert first["contributions"]  # explain=True explains even an approval


def test_review_holds_the_money_until_overridden(base_network, model):
    strict = FraudModel()
    strict.review, strict.block = 0.0, 1.01  # everything is "review"
    with TestClient(create_app(network=copy.deepcopy(base_network), model=strict)) as c:
        s, r, device = regular_pair(c)
        body = {"type": "TRANSFER", "sender": s, "receiver": r, "amount": 1000, "device": device}
        before = c.get(f"/v1/accounts/{s}").json()["balance"]
        held = c.post("/v1/transactions", json=body).json()
        assert (held["decision"], held["status"], held["sender_balance"]) == ("review", "HELD_FOR_REVIEW", before)
        sent = c.post("/v1/transactions", json=body | {"override_review": True}).json()
        assert sent["status"] == "SUCCESS" and sent["sender_balance"] < before


def test_customer_declining_an_agent_request_is_recorded(client):
    net = client.app.state.network
    s, _, device = regular_pair(client)
    agent = next(a for a, k in net.kind.items() if k == "agent")
    body = {"type": "CASH_OUT", "channel": "AGENT_REQUEST", "sender": s, "receiver": agent, "amount": 25_000,
            "device": device, "customer_declined": True}
    out = client.post("/v1/transactions", json=body).json()
    assert out["decision"] == "declined_by_customer" and out["status"] == "DECLINED"
    bad = client.post("/v1/transactions", json=body | {"type": "TRANSFER", "channel": "USSD"})
    assert bad.status_code == 422


def test_deposits_are_recorded_not_scored(client):
    net = client.app.state.network
    s, _, _ = regular_pair(client)
    agent = next(a for a, k in net.kind.items() if k == "agent")
    before = client.get(f"/v1/accounts/{s}").json()["balance"]
    out = client.post("/v1/transactions", json={
        "type": "CASH_IN", "channel": "AGENT", "sender": agent, "receiver": s, "amount": 10_000}).json()
    assert out["decision"] == "not_scored" and out["score"] is None
    assert client.get(f"/v1/accounts/{s}").json()["balance"] == before + 10_000


def test_insufficient_funds(client):
    s, r, device = regular_pair(client)
    out = client.post("/v1/transactions", json={
        "type": "TRANSFER", "sender": s, "receiver": r, "amount": 40_000_000, "device": device}).json()
    assert out["status"] in ("FAILED_FUNDS", "BLOCKED")


@pytest.mark.parametrize("change, status", [
    ({"sender": "nobody"}, 404),
    ({"receiver": "nobody"}, 404),
    ({"amount": -5}, 422),
    ({"type": "LOAN"}, 422),
    ({"timestamp": "2025-01-01T00:00:00"}, 409),
])
def test_invalid_requests(client, change, status):
    s, r, device = regular_pair(client)
    body = {"type": "TRANSFER", "sender": s, "receiver": r, "amount": 1000, "device": device} | change
    assert client.post("/v1/transactions", json=body).status_code == status


def test_self_transfer_rejected(client):
    s, _, _ = regular_pair(client)
    assert client.post("/v1/transactions", json={
        "type": "TRANSFER", "sender": s, "receiver": s, "amount": 1000}).status_code == 422


def test_bootstrap_balances_match_the_simulation(base_network):
    from momofraud.sim.config import FraudConfig, SimConfig
    from momofraud.sim.engine import simulate
    tx = simulate(SimConfig(n_users=600, days=10, seed=3, fraud=FraudConfig(adaptive_share=0.5)))["transactions"]
    last = tx.dropna(subset=["sender_balance_after"]).groupby("sender", observed=True).tail(1)
    sample = last.sample(50, random_state=0)
    for row in sample.itertuples():
        later = tx[(tx["tx_id"] > row.tx_id) & ((tx["receiver"] == row.sender) | (tx["sender"] == row.sender))]
        if later.empty:
            assert base_network.balance[str(row.sender)] == pytest.approx(row.sender_balance_after)
    assert np.isfinite(list(base_network.balance.values())).all()


def test_account_view_includes_replayed_history(client):
    s, r, _ = regular_pair(client)
    recent = client.get(f"/v1/accounts/{s}").json()["recent"]
    assert recent and all(s in (t["sender"], t["receiver"]) for t in recent)
