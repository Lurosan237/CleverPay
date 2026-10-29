"""The behavioural features must only use the past."""

import math
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from momofraud.behaviour import FEATURES, FeatureState, Transaction, compute_features
from momofraud.sim.engine import simulate
from test_simulator import SMALL

HOUR = 3600


def tx(t, sender="alice", receiver="bob", type_="TRANSFER", amount=5_000.0, status="SUCCESS",
       channel="USSD", device="phone-1", balance=50_000.0, receiver_balance=10_000.0):
    return Transaction(t, type_, channel, status, amount, sender, receiver, balance, receiver_balance, device)


def feature(state: FeatureState, record: Transaction, name: str) -> float:
    return state.features(record)[FEATURES.index(name)]


def run(state: FeatureState, *records: Transaction) -> None:
    for record in records:
        state.observe(record)


def test_first_payment_to_someone_is_new_then_known():
    state = FeatureState()
    first = tx(0)
    assert feature(state, first, "recipient_new") == 1.0
    state.observe(first)
    assert feature(state, tx(HOUR), "recipient_new") == 0.0


def test_a_transaction_never_sees_itself():
    state = FeatureState()
    record = tx(0)
    before = state.features(record)
    assert before[FEATURES.index("sender_history")] == 0.0
    assert before[FEATURES.index("sender_out_count_24h")] == 0.0


def test_new_device_and_device_age():
    state = FeatureState()
    run(state, tx(0, device="phone-1"))
    assert feature(state, tx(HOUR, device="phone-2"), "device_new") == 1.0
    run(state, tx(HOUR, type_="AIRTIME", receiver="M-airtime", device="phone-2"))  # a "warm-up" purchase
    later = tx(2 * HOUR, device="phone-2")
    assert feature(state, later, "device_new") == 0.0
    assert feature(state, later, "hours_since_device_first_seen") == pytest.approx(1.0)


def test_sim_swap_is_remembered_but_device_change_is_separate():
    state = FeatureState()
    state.observe_event(0, "alice", "SIM_SWAP")
    state.observe_event(0, "bob", "DEVICE_CHANGE")
    assert feature(state, tx(2 * HOUR), "hours_since_sim_swap_or_pin_reset") == pytest.approx(2.0)
    assert feature(state, tx(2 * HOUR, sender="bob", receiver="carol"),
                   "hours_since_sim_swap_or_pin_reset") == 24 * 30
    assert feature(state, tx(2 * HOUR, sender="bob", receiver="carol"),
                   "hours_since_device_change") == pytest.approx(2.0)


def test_agent_decline_rate_uses_past_requests_in_the_last_day():
    state = FeatureState()
    for i in range(10):
        run(state, tx(i * 60, sender=f"c{i}", receiver="agent-X", type_="CASH_OUT",
                      channel="AGENT_REQUEST", status="DECLINED" if i < 8 else "SUCCESS"))
    now = tx(HOUR, sender="victim", receiver="agent-X", type_="CASH_OUT", channel="AGENT_REQUEST")
    assert feature(state, now, "agent_decline_rate_24h") == pytest.approx(8 / 15)
    tomorrow = tx(HOUR + 86_400, sender="victim", receiver="agent-X", type_="CASH_OUT",
                  channel="AGENT_REQUEST")
    assert feature(state, tomorrow, "agent_decline_rate_24h") == 0.0


def test_receiver_that_gets_money_from_strangers_and_withdraws_it():
    state = FeatureState()
    for i in range(4):
        run(state, tx(i * HOUR, sender=f"victim{i}", receiver="mule", amount=10_000))
    run(state, tx(5 * HOUR, sender="mule", receiver="agent", type_="CASH_OUT", amount=30_000))
    check = tx(6 * HOUR, sender="victim9", receiver="mule")
    assert feature(state, check, "receiver_stranger_share_7d") == 1.0
    assert feature(state, check, "receiver_distinct_senders_7d") == 4.0
    assert feature(state, check, "receiver_cashout_ratio_7d") == pytest.approx(0.75)


def test_failed_payments_do_not_count_as_known_recipients():
    state = FeatureState()
    run(state, tx(0, status="FAILED_FUNDS"))
    assert feature(state, tx(HOUR), "recipient_new") == 1.0


def test_amount_zscore_flags_unusually_large_amounts():
    state = FeatureState()
    run(state, *[tx(i * HOUR, amount=5_000 + 100 * (i % 3)) for i in range(10)])
    assert feature(state, tx(20 * HOUR, amount=5_000), "amount_zscore") == pytest.approx(0, abs=0.5)
    assert feature(state, tx(20 * HOUR, amount=200_000), "amount_zscore") > 3


@pytest.fixture(scope="module")
def world():
    return simulate(replace(SMALL, n_users=800, days=14))


def test_compute_features_shape(world):
    features = compute_features(world)
    scored = world["transactions"]["type"].isin(["TRANSFER", "CASH_OUT"]).sum()
    assert list(features.columns) == FEATURES
    assert len(features) == scored
    assert np.isfinite(features.to_numpy()).all()


def test_features_do_not_change_when_the_future_is_removed(world):
    """The leakage test: cut the world off at day 7 and recompute. Every transaction
    before the cut must get exactly the same features as with the full history."""
    full = compute_features(world)
    cutoff = world["transactions"]["timestamp"].min().normalize() + pd.Timedelta(days=7)
    truncated = {
        "transactions": world["transactions"][world["transactions"]["timestamp"] < cutoff],
        "account_events": world["account_events"][world["account_events"]["timestamp"] < cutoff],
        "accounts": world["accounts"],
    }
    past = compute_features(truncated)
    assert len(past) > 1000
    pd.testing.assert_frame_equal(full.loc[past.index], past)


def test_cap_for_never():
    state = FeatureState()
    assert feature(state, tx(0), "hours_since_sender_last_tx") == 24 * 30
    assert not math.isnan(feature(state, tx(0, balance=math.nan), "amount_to_balance"))
