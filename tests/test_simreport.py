from dataclasses import replace

import pytest

from momofraud.sim.engine import simulate
from momofraud.simreport import describe, to_markdown
from test_simulator import SMALL


@pytest.fixture(scope="module")
def world():
    return simulate(replace(SMALL, n_users=800, days=10))


def test_describe_reports_calibration_and_fraud(world):
    d = describe(world)
    assert d["customers"] == 800 and d["days"] == 10
    assert 0 < d["legit_failed_share"] < 0.1
    assert {row["scenario"] for row in d["victim_transactions"]} == {
        "account_takeover", "withdrawal_request", "wrong_transfer"}


def test_markdown_renders(world):
    d = describe(world)
    text = to_markdown({"worlds": {"naive": d, "adaptive": d}})
    assert "# Simulator report" in text and "| account_takeover |" in text
