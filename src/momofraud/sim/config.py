"""Simulation parameters, with the published figures they were calibrated against.

Calibration anchors (Cameroon / CEMAC):
- Average mobile money transaction: about 10,000 FCFA in 2023 (CFA 22.1 trillion over
  2.2 billion transactions, BEAC via Business in Cameroon).
- Airtime purchases: average 570 FCFA; other merchant payments about 4,000 FCFA (CEMAC 2024).
- Money transfer tax (TTA): 0.2% on transfers and withdrawals since January 2022.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRANSFER_TAX = 0.002  # applied to TRANSFER and CASH_OUT

REGIONS = {  # relative population weight of the account holders' home towns
    "Douala": 0.24, "Yaoundé": 0.22, "Garoua": 0.08, "Bafoussam": 0.08, "Bamenda": 0.07,
    "Maroua": 0.07, "Ngaoundéré": 0.06, "Bertoua": 0.06, "Ebolowa": 0.06, "Kribi": 0.06,
}


@dataclass(frozen=True)
class Profile:
    """Typical behaviour of one kind of account holder. Rates are per day,
    amounts are lognormal with the given median (FCFA) and spread (sigma)."""

    share: float
    initial_balance: float
    cash_in: tuple[float, float, float]        # (rate, median, sigma)
    transfer: tuple[float, float, float]
    airtime: tuple[float, float, float]
    merchant: tuple[float, float, float]
    cash_out: tuple[float, float, float]
    monthly_income: float = 0.0               # paid in the last 3 days of the month
    bills: tuple[float, ...] = ()              # monthly bill amounts


PROFILES = {
    "student": Profile(0.24, 8_000, (0.10, 5_000, 0.6), (0.12, 2_500, 0.7), (0.45, 350, 0.6),
                       (0.15, 1_000, 0.7), (0.10, 4_000, 0.6)),
    "salaried": Profile(0.20, 120_000, (0.05, 15_000, 0.7), (0.30, 10_000, 0.8), (0.40, 700, 0.6),
                        (0.25, 3_500, 0.8), (0.20, 15_000, 0.7), monthly_income=180_000,
                        bills=(12_000, 6_000)),
    "trader": Profile(0.26, 40_000, (0.45, 15_000, 0.8), (0.35, 12_000, 0.9), (0.40, 500, 0.6),
                      (0.20, 3_500, 0.9), (0.35, 18_000, 0.8), bills=(8_000,)),
    "farmer": Profile(0.20, 15_000, (0.08, 10_000, 0.8), (0.08, 4_000, 0.7), (0.25, 300, 0.5),
                      (0.05, 1_500, 0.7), (0.10, 8_000, 0.7)),
    "retired": Profile(0.10, 50_000, (0.04, 8_000, 0.6), (0.06, 6_000, 0.7), (0.20, 400, 0.5),
                       (0.08, 2_000, 0.7), (0.12, 10_000, 0.6), monthly_income=80_000, bills=(6_000,)),
}

# Hourly activity profile (Africa/Douala local time): quiet nights, busy days
HOURLY_WEIGHTS = [0.2, 0.1, 0.05, 0.05, 0.1, 0.4, 1.2, 2.5, 4.0, 5.0, 5.5, 5.5,
                  5.5, 5.5, 5.5, 5.5, 5.5, 6.0, 6.5, 6.0, 4.5, 3.0, 1.5, 0.6]


@dataclass(frozen=True)
class FraudConfig:
    """How much fraud to inject, and how sophisticated it is.

    adaptive_share is the fraction of attacks that use the adaptive strategy:
    0.0 gives PaySim-like naive fraud, 1.0 gives fraudsters who try to blend in.

    Attack rates are deliberately higher than real-world rates (roughly 1 in 1,500
    transactions is fraudulent) so a 90-day run has a few thousand fraudulent
    transactions to train and evaluate on.
    """

    adaptive_share: float = 0.5
    # Share of takeovers and "wrong transfer" scams that use *rented* accounts: ordinary
    # customers' accounts with years of normal history, rented out to the fraudster, who
    # lets the money sit instead of withdrawing it. The blind spot the stage 5 game found.
    # 0 keeps every earlier world exactly as it was.
    rented_share: float = 0.0
    takeovers_per_10k_users_per_month: float = 120.0
    withdrawal_campaigns_per_month: float = 15.0
    wrong_transfer_victims_per_10k_users_per_month: float = 120.0
    # Share of "wrong transfer" victims who dial the scammer's code, leaking their PIN
    wrong_transfer_code_leak: float = 0.3
    mules: int = 600
    rogue_agents: int = 12


@dataclass(frozen=True)
class SimConfig:
    n_users: int = 20_000
    days: int = 90
    start: str = "2026-01-01"
    seed: int = 42
    users_per_agent: int = 100
    n_shops: int = 400
    # Legitimate events that look suspicious, so a model can't just learn "new device = fraud"
    legit_device_change_rate_per_month: float = 0.01
    # People forget their PIN, and replace lost or broken SIMs: the same account events a
    # fraudster triggers, so "recent PIN reset" or "recent SIM swap" alone can't mean fraud
    legit_pin_reset_rate_per_month: float = 0.02
    legit_sim_replacement_rate_per_month: float = 0.005
    # Optional population shift for drift experiments: from `promo_start_day`, over one week,
    # this share of customers gets a new phone (think of a handset promotion). Drawn from its own
    # random stream, so the world is identical to the unshifted one until the promotion starts.
    promo_start_day: int | None = None
    promo_new_phone_share: float = 0.0
    # Chance that someone who just received money cashes out soon after (like a mule would)
    cash_out_after_receipt: float = 0.15
    # Chance that someone sending or withdrawing more than they have lowers the amount
    adjust_to_balance: float = 0.8
    # Chance that someone who can't afford a fixed-amount payment deposits cash first
    top_up_before_paying: float = 0.75
    # Chance that someone whose payment failed tops up at an agent and tries again
    top_up_after_failure: float = 0.6
    fraud: FraudConfig = field(default_factory=FraudConfig)
