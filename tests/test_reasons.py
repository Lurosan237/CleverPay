import numpy as np

from momofraud.behaviour import FEATURES
from momofraud.serving.reasons import _duration, reasons


def values(**overrides) -> list[float]:
    base = dict.fromkeys(FEATURES, 0.0)
    base.update({"is_transfer": 1.0, "hours_since_sim_swap_or_pin_reset": 720.0,
                 "hours_since_device_change": 720.0, "hours_since_sender_last_tx": 1.0,
                 "sender_history": 5.0, "receiver_age_days": 900.0, "hour": 12.0})
    base.update(overrides)
    return [base[f] for f in FEATURES]


def contributions(*names: str) -> np.ndarray:
    c = np.zeros(len(FEATURES))
    for rank, name in enumerate(names):
        c[FEATURES.index(name)] = 3.0 - rank * 0.5
    return c


def test_durations():
    assert _duration(10 / 60, "en") == "10 min"
    assert _duration(5, "en") == "5 h"
    assert _duration(24 * 5, "fr") == "5 jours"


def test_strongest_reasons_first_and_only_risky_ones():
    v = values(recipient_new=1.0, hours_since_sim_swap_or_pin_reset=0.25, receiver_age_days=0.01)
    c = contributions("hours_since_sim_swap_or_pin_reset", "receiver_age_days", "recipient_new")
    c[FEATURES.index("amount_zscore")] = -2.0  # lowers risk: never a reason
    out = reasons(c, v)
    assert [r["feature"] for r in out] == ["hours_since_sim_swap_or_pin_reset", "receiver_age_days", "recipient_new"]
    assert out[0]["text"] == "PIN reset or SIM swap 15 min ago"


def test_no_reason_when_value_is_unremarkable():
    out = reasons(contributions("recipient_new"), values(recipient_new=0.0))
    assert out == []


def test_withdrawals_talk_about_the_agent_not_the_recipient():
    v = values(is_transfer=0.0, recipient_new=1.0, agent_new_for_sender=1.0, agent_decline_rate_24h=0.8)
    out = reasons(contributions("recipient_new", "agent_decline_rate_24h", "agent_new_for_sender"), v)
    texts = [r["text"] for r in out]
    assert "First payment to this number" not in texts
    assert "Customers declined most of this agent's withdrawal requests today" in texts
    assert "First withdrawal with this agent" in texts


def test_french():
    out = reasons(contributions("recipient_new"), values(recipient_new=1.0), lang="fr")
    assert out[0]["text"] == "Premier envoi vers ce numéro"
