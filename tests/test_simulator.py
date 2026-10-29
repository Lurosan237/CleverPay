"""Invariants the simulated data must satisfy. Run on a small population for speed."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from momofraud.sim.config import TRANSFER_TAX, FraudConfig, SimConfig
from momofraud.sim.engine import simulate

SMALL = SimConfig(n_users=1500, days=21, seed=7,
                  fraud=FraudConfig(takeovers_per_10k_users_per_month=400,
                                    wrong_transfer_victims_per_10k_users_per_month=400,
                                    withdrawal_campaigns_per_month=20, mules=80, rogue_agents=4))


@pytest.fixture(scope="module")
def sim():
    return simulate(SMALL)


@pytest.fixture(scope="module")
def tx(sim):
    return sim["transactions"]


def test_produces_all_scenarios_and_strategies(tx):
    fraud = tx[tx["is_fraud"] == 1]
    assert set(fraud["scenario"]) == {"account_takeover", "withdrawal_request", "wrong_transfer"}
    assert set(fraud["strategy"]) == {"naive", "adaptive"}
    assert fraud[["scenario", "role", "strategy"]].notna().all().all()
    assert tx.loc[tx["is_fraud"] == 0, ["scenario", "role", "strategy"]].isna().all().all()


def test_balances_never_negative(tx):
    for col in ("sender_balance_after", "receiver_balance_after"):
        assert (tx[col].dropna() >= 0).all()


def test_successful_transactions_move_exactly_amount_plus_fee(tx):
    ok = tx[(tx["status"] == "SUCCESS") & tx["sender_balance_before"].notna()]
    expected = ok["sender_balance_before"] - ok["amount"] - ok["fee"]
    assert np.allclose(ok["sender_balance_after"], expected)
    received = tx[(tx["status"] == "SUCCESS") & tx["receiver_balance_before"].notna()]
    assert np.allclose(received["receiver_balance_after"],
                       received["receiver_balance_before"] + received["amount"])


def test_failed_and_declined_transactions_change_nothing(tx):
    failed = tx[(tx["status"] != "SUCCESS") & tx["sender_balance_before"].notna()]
    assert len(failed) > 0
    assert np.allclose(failed["sender_balance_after"], failed["sender_balance_before"])
    assert (failed["fee"] == 0).all()


def test_each_balance_continues_from_the_previous_transaction(tx):
    """The strongest consistency check: for every account, each row's balance before
    equals the balance after of that account's previous row (unlike PaySim)."""
    sides = []
    for side in ("sender", "receiver"):
        part = tx[["tx_id", side, f"{side}_balance_before", f"{side}_balance_after"]].dropna()
        part.columns = ["tx_id", "account", "before", "after"]
        sides.append(part)
    ledger = pd.concat(sides).sort_values(["account", "tx_id"], kind="stable")
    previous_after = ledger.groupby("account", observed=True)["after"].shift()
    has_previous = previous_after.notna()
    assert np.allclose(ledger.loc[has_previous, "before"], previous_after[has_previous])


def test_transfer_tax(tx):
    ok = tx[(tx["status"] == "SUCCESS") & tx["type"].isin(["TRANSFER", "CASH_OUT"])]
    assert np.allclose(ok["fee"], np.ceil(ok["amount"] * TRANSFER_TAX))
    other = tx[~tx["type"].isin(["TRANSFER", "CASH_OUT"])]
    assert (other["fee"] == 0).all()


def test_naive_takeovers_empty_the_account_and_adaptive_ones_do_not(tx):
    debits = tx[(tx["scenario"] == "account_takeover") & (tx["role"] == "victim_debit")
                & (tx["status"] == "SUCCESS")]
    taken = (debits["amount"] + debits["fee"]) / debits["sender_balance_before"]
    naive = taken[debits["strategy"] == "naive"]
    adaptive = taken[debits["strategy"] == "adaptive"]
    assert len(naive) and len(adaptive)
    assert (naive > 0.99).all()
    assert (adaptive <= 0.95 + 1e-9).all()


def test_takeover_transactions_come_from_a_device_the_owner_never_used(tx):
    stolen = tx[tx["scenario"] == "account_takeover"]
    owner_devices = set(zip(tx.loc[tx["is_fraud"] == 0, "sender"], tx.loc[tx["is_fraud"] == 0, "device"],
                            strict=True))
    assert len(stolen) > 0
    assert not any(
        (r.sender, r.device) in owner_devices for r in stolen.itertuples() if r.role != "mule_cashout"
    )


def test_nobody_sends_money_to_themselves(tx):
    assert (tx["sender"].astype(str) != tx["receiver"].astype(str)).all()


def test_owner_cannot_transact_while_sim_is_swapped(sim, tx):
    events = sim["account_events"]
    swaps = events[events["event"] == "SIM_SWAP"]
    restores = events[events["event"] == "SIM_RESTORED"]
    assert len(swaps) > 0
    for swap in swaps.itertuples():
        restored = restores[(restores["account"] == swap.account) & (restores["timestamp"] > swap.timestamp)]
        end = restored["timestamp"].min()
        window = tx[(tx["sender"] == swap.account) & (tx["timestamp"] > swap.timestamp)
                    & (tx["timestamp"] < end) & (tx["is_fraud"] == 0)]
        assert window.empty


def test_withdrawal_campaigns_are_mostly_declined(tx):
    requests = tx[tx["scenario"] == "withdrawal_request"]
    assert (requests["channel"] == "AGENT_REQUEST").all()
    assert (requests["status"] == "DECLINED").mean() > 0.85


def test_legitimate_data_has_hard_negatives(sim, tx):
    """Legit phone changes and quick withdrawals exist, so neither is a fraud giveaway."""
    events = sim["account_events"]
    assert (events["event"] == "DEVICE_CHANGE").sum() > 0
    # Some PIN resets and SIM swaps belong to the real owner: they are not followed by fraud
    fraud_accounts = set(tx.loc[tx["scenario"] == "account_takeover", "sender"].astype(str))
    security = events[events["event"].isin(["PIN_RESET", "SIM_SWAP"])]
    assert (~security["account"].isin(fraud_accounts)).sum() > 0
    legit_requests = tx[(tx["is_fraud"] == 0) & (tx["status"] == "DECLINED")]
    assert len(legit_requests) > 0


def test_naive_only_configuration_has_no_adaptive_fraud():
    cfg = replace(SMALL, n_users=600, days=10, fraud=replace(SMALL.fraud, adaptive_share=0.0))
    fraud = simulate(cfg)["transactions"].query("is_fraud == 1")
    assert len(fraud) > 0 and set(fraud["strategy"]) == {"naive"}


def test_same_seed_same_data():
    cfg = replace(SMALL, n_users=400, days=7)
    a, b = simulate(cfg)["transactions"], simulate(cfg)["transactions"]
    pd.testing.assert_frame_equal(a, b)


def test_legit_failure_rate_is_realistic(tx):
    legit = tx[tx["is_fraud"] == 0]
    assert (legit["status"] == "FAILED_FUNDS").mean() < 0.08


def test_tiny_world_still_works():
    cfg = replace(SMALL, n_users=300, days=5)
    accounts = simulate(cfg)["accounts"]
    assert 0 < accounts["rogue_agent"].sum() <= (accounts["kind"] == "agent").sum() // 2
