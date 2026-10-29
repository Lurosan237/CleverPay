"""Turn SHAP contributions into reasons a customer-support agent (or a player) can read.

Only features that pushed the score *towards* fraud are turned into reasons, strongest
first. Each reason is written from the feature's actual value, in English or French.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from momofraud.behaviour import CAP_HOURS, FEATURES

Lang = str  # "en" | "fr"


def _duration(hours: float, lang: Lang) -> str:
    minutes = hours * 60
    if minutes < 90:
        n = max(1, round(minutes))
        return f"{n} min"
    if hours < 48:
        n = round(hours)
        return f"{n} h"
    n = round(hours / 24)
    return f"{n} {'days' if lang == 'en' else 'jours'}"


def _pct(x: float) -> str:
    return f"{x:.0%}"


# feature -> function(value, all feature values by name, lang) -> text, or None if not worth saying
Template = Callable[[float, dict[str, float], Lang], str | None]

def _t(lang: Lang, en: str, fr: str) -> str:
    return en if lang == "en" else fr


TEMPLATES: dict[str, Template] = {
    "device_new": lambda v, f, lang: _t(
        lang, "First transaction from this phone on this account",
        "Première transaction depuis ce téléphone sur ce compte") if v >= 0.5 else None,
    "hours_since_device_first_seen": lambda v, f, lang: _t(
        lang, f"This phone was first used on the account {_duration(v, lang)} ago",
        f"Ce téléphone est utilisé sur le compte depuis {_duration(v, lang)} seulement",
    ) if v < 24 * 14 and f.get("device_new", 0) < 0.5 else None,
    "hours_since_sim_swap_or_pin_reset": lambda v, f, lang: _t(
        lang, f"PIN reset or SIM swap {_duration(v, lang)} ago",
        f"Code PIN réinitialisé ou carte SIM changée il y a {_duration(v, lang)}") if v < CAP_HOURS else None,
    "hours_since_device_change": lambda v, f, lang: _t(
        lang, f"Phone changed {_duration(v, lang)} ago",
        f"Changement de téléphone il y a {_duration(v, lang)}") if v < CAP_HOURS else None,
    # For withdrawals the "recipient" is an agent: agent_new_for_sender says it better
    "recipient_new": lambda v, f, lang: _t(
        lang, "First payment to this number", "Premier envoi vers ce numéro",
    ) if v >= 0.5 and f.get("is_transfer", 1) >= 0.5 else None,
    "receiver_age_days": lambda v, f, lang: _t(
        lang, f"Recipient account opened {_duration(v * 24, lang)} ago",
        f"Compte du destinataire ouvert il y a {_duration(v * 24, lang)}") if v < 90 else None,
    "receiver_stranger_share_7d": lambda v, f, lang: _t(
        lang, f"{_pct(v)} of the money the recipient received this week came from people they don't know",
        f"{_pct(v)} de l'argent reçu par le destinataire cette semaine vient d'inconnus",
    ) if v >= 0.3 else None,
    "receiver_distinct_senders_7d": lambda v, f, lang: _t(
        lang, f"The recipient received money from {int(v)} different people this week",
        f"Le destinataire a reçu de l'argent de {int(v)} personnes différentes cette semaine",
    ) if v >= 4 else None,
    "receiver_cashout_ratio_7d": lambda v, f, lang: _t(
        lang, f"The recipient withdrew {_pct(min(v, 1))} of what they received this week",
        f"Le destinataire a retiré {_pct(min(v, 1))} de ce qu'il a reçu cette semaine") if v >= 0.5 else None,
    "receiver_in_count_24h": lambda v, f, lang: _t(
        lang, f"The recipient received {int(v)} transfers in the last 24 h",
        f"Le destinataire a reçu {int(v)} transferts en 24 h") if v >= 3 else None,
    # The feature is smoothed (declined / (requests + 5)), so it is described, not quoted as a percentage
    "agent_decline_rate_24h": lambda v, f, lang: _t(
        lang, f"Customers declined {'most' if v >= 0.5 else 'many'} of this agent's withdrawal requests today",
        f"Les clients ont refusé {'la plupart' if v >= 0.5 else 'beaucoup'} des demandes de retrait de cet agent "
        "aujourd'hui",
    ) if v >= 0.2 else None,
    "agent_requests_1h": lambda v, f, lang: _t(
        lang, f"This agent sent {int(v)} withdrawal requests in the last hour",
        f"Cet agent a envoyé {int(v)} demandes de retrait dans la dernière heure") if v >= 5 else None,
    "agent_new_for_sender": lambda v, f, lang: _t(
        lang, "First withdrawal with this agent", "Premier retrait chez cet agent") if v >= 0.5 else None,
    "region_mismatch": lambda v, f, lang: _t(
        lang, "The other party is in a different town", "L'autre partie est dans une autre ville",
    ) if v >= 0.5 else None,
    "empties_account": lambda v, f, lang: _t(
        lang, "Empties the account", "Vide le compte") if v >= 0.5 else None,
    "amount_to_balance": lambda v, f, lang: _t(
        lang, f"Moves {_pct(min(v, 1))} of the balance", f"Transfère {_pct(min(v, 1))} du solde",
    ) if v >= 0.5 and f.get("empties_account", 0) < 0.5 else None,
    "amount_zscore": lambda v, f, lang: _t(
        lang, "Much larger than this customer's usual amounts",
        "Bien plus élevé que les montants habituels de ce client") if v >= 2 else None,
    "hour": lambda v, f, lang: _t(
        lang, f"Unusual time of day ({int(v):02d}:00)", f"Heure inhabituelle ({int(v):02d}h)",
    ) if v < 6 or v >= 22 else None,
    "sender_history": lambda v, f, lang: _t(
        lang, "Very little history on this account", "Très peu d'historique sur ce compte",
    ) if math.expm1(v) < 10 else None,
    "sender_out_count_24h": lambda v, f, lang: _t(
        lang, f"{int(v)} outgoing transactions in the last 24 h", f"{int(v)} opérations sortantes en 24 h",
    ) if v >= 4 else None,
    "hours_since_sender_last_tx": lambda v, f, lang: _t(
        lang, f"First activity in {_duration(v, lang)}", f"Première activité depuis {_duration(v, lang)}",
    ) if v >= 24 * 7 else None,
}


def reasons(contributions, values: list[float], lang: Lang = "en", top: int = 3,
            min_contribution: float = 0.05) -> list[dict]:
    """The strongest reasons this transaction looks risky, as readable sentences."""
    by_name = dict(zip(FEATURES, values, strict=True))
    order = sorted(range(len(FEATURES)), key=lambda i: contributions[i], reverse=True)
    out = []
    for i in order:
        if contributions[i] < min_contribution or len(out) >= top:
            break
        name = FEATURES[i]
        template = TEMPLATES.get(name)
        text = template(values[i], by_name, lang) if template else None
        if text:
            out.append({"feature": name, "text": text, "contribution": round(float(contributions[i]), 3)})
    return out
