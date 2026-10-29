"""The game: play the fraudster against the real scoring model.

Three missions, one per scam. Every money movement goes through exactly the same
decision path as the API (service.process). Each scored attempt is logged with its
features, so what players discover can be used to retrain the model.

CleverPay is a fictional brand in this game, not affiliated with any real company.
"""

from __future__ import annotations

import copy
import json
import random
import secrets
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from momofraud.behaviour import FEATURES
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network, NetworkError
from momofraud.serving.service import Outcome, new_number, process

MINUTE, HOUR, DAY = 60, 3600, 86_400
RENT_COST, SIM_COST = 10_000, 500   # renting an aged account isn't free; neither is a new SIM
WAITS = {"10m": 10 * MINUTE, "2h": 2 * HOUR, "1d": DAY}
NAMES = ["Mama Ngono", "Papa Bello", "Tantine Clarisse", "Grand-frère Serge", "Amina", "Jean-Paul", "Esther",
         "Moussa", "Hawa", "Didier", "Ruth", "Oumarou"]

TEXT = {
    "en": {
        "takeover_brief": "You got {name}'s CleverPay PIN {how}. Balance: {balance} FCFA. Move as much as you "
                          "can to accounts you control before {deadline}. A new number costs 500 FCFA, renting an old "
                          "account 10,000. A block freezes the account.",
        "how_pin": "by calling them as a fake CleverPay agent",
        "how_sim": "by swapping her SIM card",
        "rogue_brief": "You are agent {agent} in {region}. Send withdrawal requests to customers: anyone who "
                       "approves by mistake pays you. Three blocks and CleverPay suspends you.",
        "wrong_brief": "You call people and say you sent them money by mistake. A new number costs 500 FCFA, "
                       "renting an old account 10,000. Three blocks and you're out.",
        "wait": "You wait {what}.",
        "airtime": "You buy {amount} FCFA of airtime from the victim's account with your phone. Not checked.",
        "opened": "You open a new account: {number}.",
        "rented": "You rent {number}, an old account with years of normal activity, for {cost} FCFA.",
        "approve": "{amount} FCFA sent to {to}. Approved.",
        "review_takeover": "CleverPay asks the real owner to confirm {amount} FCFA. They refuse.",
        "review_request": "CleverPay warns the customer about this withdrawal. They cancel.",
        "review_victim_cancels": "CleverPay warns the victim: \"You have never sent money to this number. Did someone "
                                 "call you about a mistake?\" They cancel.",
        "review_victim_sends": "CleverPay shows the victim a warning, but they send it anyway.",
        "block": "Blocked: {amount} FCFA to {to}.",
        "frozen": "The account is frozen. Mission over.",
        "suspended": "CleverPay suspends you. Mission over.",
        "burned": "Number {number} is flagged: you need a new one.",
        "no_funds": "Not enough money in the account for {amount} FCFA.",
        "hung_up": "{name} doesn't believe you and hangs up.",
        "believes": "{name} believes you and sends {amount} FCFA.",
        "batch": "{sent} requests sent: {declined} declined, {approved} approved by mistake.",
        "time_up": "Time is up.",
        "sim_back": "The owner got their SIM back. Mission over.",
        "owner_noticed": "The owner noticed. Mission over.",
        "tips_takeover": "Never share your PIN, even with someone who says they work for your operator. If your phone "
                         "suddenly loses network, call your operator at once: it may be a SIM swap.",
        "tips_rogue": "Never approve a withdrawal request you didn't start, at an agent you are not standing in front "
                      "of.",
        "tips_wrong": "If someone says they sent you money by mistake, check your real balance in the app first. A "
                      "text message is not proof. Never dial a code a stranger gives you.",
    },
    "fr": {
        "takeover_brief": "Vous avez obtenu le code PIN CleverPay de {name} {how}. Solde : {balance} FCFA. "
                          "Transférez le plus possible vers vos comptes avant {deadline}. Un nouveau numéro coûte "
                          "500 FCFA, louer un vieux compte 10 000. Un blocage gèle le compte.",
        "how_pin": "en l'appelant comme faux agent CleverPay",
        "how_sim": "en faisant changer sa carte SIM",
        "rogue_brief": "Vous êtes l'agent {agent} à {region}. Envoyez des demandes de retrait : chaque client qui "
                       "accepte par erreur vous paie. Trois blocages et CleverPay vous suspend.",
        "wrong_brief": "Vous appelez des gens en disant leur avoir envoyé de l'argent par erreur. Un nouveau "
                       "numéro coûte 500 FCFA, louer un vieux compte 10 000. Trois blocages et c'est fini.",
        "wait": "Vous attendez {what}.",
        "airtime": "Vous achetez {amount} FCFA de crédit depuis le compte de la victime avec votre téléphone. "
                   "Pas de contrôle.",
        "opened": "Vous ouvrez un nouveau compte : {number}.",
        "rented": "Vous louez {number}, un vieux compte avec des années d'activité normale, pour {cost} FCFA.",
        "approve": "{amount} FCFA envoyés à {to}. Accepté.",
        "review_takeover": "CleverPay demande au vrai titulaire du compte de confirmer {amount} FCFA. Il refuse.",
        "review_request": "CleverPay avertit le client au sujet de ce retrait. Il annule.",
        "review_victim_cancels": "CleverPay avertit la victime : « Vous n'avez jamais envoyé d'argent à ce numéro. "
                                 "Quelqu'un vous a-t-il appelé pour une erreur ? » Elle annule.",
        "review_victim_sends": "CleverPay avertit la victime, mais elle envoie quand même.",
        "block": "Bloqué : {amount} FCFA vers {to}.",
        "frozen": "Le compte est gelé. Mission terminée.",
        "suspended": "CleverPay vous suspend. Mission terminée.",
        "burned": "Le numéro {number} est signalé : il vous en faut un nouveau.",
        "no_funds": "Solde insuffisant pour {amount} FCFA.",
        "hung_up": "{name} ne vous croit pas et raccroche.",
        "believes": "{name} vous croit et envoie {amount} FCFA.",
        "batch": "{sent} demandes envoyées : {declined} refusées, {approved} acceptées par erreur.",
        "time_up": "Temps écoulé.",
        "sim_back": "Le titulaire a récupéré sa carte SIM. Mission terminée.",
        "owner_noticed": "Le titulaire s'en est rendu compte. Mission terminée.",
        "tips_takeover": "Ne communiquez jamais votre code PIN, même à quelqu'un qui dit travailler pour votre "
                         "opérateur. Si votre téléphone perd soudain le réseau, appelez votre opérateur : c'est peut-"
                         "être un changement de SIM frauduleux.",
        "tips_rogue": "N'acceptez jamais une demande de retrait que vous n'avez pas faite, chez un agent devant qui "
                      "vous n'êtes pas.",
        "tips_wrong": "Si quelqu'un dit vous avoir envoyé de l'argent par erreur, vérifiez d'abord votre vrai solde "
                      "dans l'application. Un SMS n'est pas une preuve. Ne composez jamais un code donné par un "
                      "inconnu.",
    },
}
WAIT_LABEL = {"en": {"10m": "10 minutes", "2h": "2 hours", "1d": "a day"},
              "fr": {"10m": "10 minutes", "2h": "2 heures", "1d": "une journée"}}


class GameError(NetworkError):
    """An action that isn't allowed right now (mission over, wrong mission, unknown account...)."""


@dataclass
class Session:
    id: str
    net: Network                 # each game is played in its own copy of the network
    rng: random.Random
    mission: str
    lang: str
    player: str
    started_t: int
    deadline_t: int
    max_strikes: int
    end_text_key: str            # why the mission ends when time runs out
    stolen: float = 0.0
    costs: float = 0.0
    strikes: int = 0
    attempts: int = 0
    over: bool = False
    outcome: str | None = None   # time_up | caught | quit
    log: list[dict] = field(default_factory=list)
    caught_by: Counter = field(default_factory=Counter)
    victim: str | None = None
    victim_name: str | None = None
    attacker_device: str | None = None
    agent: str | None = None
    owned: list[str] = field(default_factory=list)   # accounts the player controls
    rented: set[str] = field(default_factory=set)
    burned: set[str] = field(default_factory=set)
    called: set[str] = field(default_factory=set)


class Game:
    """Runs game sessions. Each session gets its own copy of the network, so players don't
    share a clock or interfere with each other, and the API's network is never touched."""

    def __init__(self, network: Network, model: FraudModel, log_file: Path | None = None, seed: int | None = None,
                 max_sessions: int = 8):
        self.base, self.model, self.log_file = network, model, log_file
        self.rng = random.Random(seed)
        self.max_sessions = max_sessions
        self.sessions: dict[str, Session] = {}
        self.leaderboard: dict[str, list[dict]] = {"takeover": [], "rogue_agent": [], "wrong_transfer": []}
        self.customers = [a for a, k in network.kind.items() if k == "customer"]
        self.agents = [a for a, k in network.kind.items() if k == "agent"]
        self.airtime_merchant = next(a for a, k in network.kind.items() if k == "merchant")

    # -- helpers -------------------------------------------------------------------------------
    def t(self, s: Session, key: str, **kw) -> str:
        """Narration in the session's language, with amounts written the local way (5,000 / 5 000)."""
        sep = "," if s.lang == "en" else "\u202f"
        kw = {k: f"{v:,.0f}".replace(",", sep) if isinstance(v, int | float) and not isinstance(v, bool) else v
              for k, v in kw.items()}
        return TEXT[s.lang][key].format(**kw)

    def _event(self, s: Session, kind: str, text: str, **extra) -> dict:
        event = {"time": s.net.timestamp(s.net.now), "kind": kind, "text": text, **extra}
        s.log.append(event)
        return event

    def _advance(self, s: Session, seconds: int) -> int:
        """Move the clock forward; end the mission if the deadline passes."""
        t = s.net.now + max(1, int(seconds))
        if t >= s.deadline_t:
            s.net.now = max(s.net.now, s.deadline_t)
            self._finish(s, "time_up")
            self._event(s, "info", self.t(s, s.end_text_key))
            return -1
        s.net.now = t
        return t

    def _finish(self, s: Session, outcome: str) -> None:
        if s.over:
            return
        s.over, s.outcome = True, outcome
        board = self.leaderboard[s.mission]
        board.append({"player": s.player, "profit": round(s.stolen - s.costs), "stolen": round(s.stolen),
                      "attempts": s.attempts, "outcome": outcome})
        board.sort(key=lambda r: -r["profit"])
        del board[10:]

    def _require_open(self, s: Session, mission: str | None = None) -> None:
        if s.over:
            raise GameError("this mission is over: start a new one", status=409)
        if mission and s.mission != mission:
            raise GameError(f"this action is not part of the {s.mission} mission")

    def _log_attempt(self, s: Session, outcome: Outcome, action: dict) -> None:
        if self.log_file is None or outcome.features is None:
            return
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        row = {"session": s.id, "mission": s.mission, "time": outcome.timestamp, "decision": outcome.decision,
               "score": outcome.score, "action": action, "features": dict(zip(FEATURES, outcome.features, strict=True))}
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def _pick_customer(self, s: Session, min_balance: float = 0, exclude: set[str] = frozenset(),
                       region: str | None = None, needs_contacts: bool = False) -> str:
        for _ in range(5000):
            a = s.rng.choice(self.customers)
            if a in exclude or s.net.balance.get(a, 0) < min_balance:
                continue
            if region and s.net.region.get(a) != region:
                continue
            if needs_contacts:
                sent = {e["receiver"] for e in s.net.recent.get(a, [])
                        if e["sender"] == a and e["type"] == "TRANSFER"}
                if len(sent) < 2:
                    continue
            return a
        raise GameError("could not find a suitable account in this network", status=500)

    def _open(self, s: Session, rented: bool) -> str:
        if rented:
            number = self._pick_customer(s, exclude={s.victim, *s.owned} if s.victim else set(s.owned))
            s.rented.add(number)
            s.costs += RENT_COST
            self._event(s, "info", self.t(s, "rented", number=number, cost=RENT_COST))
        else:
            number = new_number(s.net, seed=s.rng.randrange(10**9))
            s.net.open_account(number, "customer", "Douala", s.net.now)
            s.costs += SIM_COST
            self._event(s, "info", self.t(s, "opened", number=number))
        s.owned.append(number)
        return number

    def _scored(self, s: Session, outcome: Outcome, amount: float, to: str, action: dict) -> None:
        """Book-keeping shared by every scored attempt."""
        s.attempts += 1
        self._log_attempt(s, outcome, action)
        if outcome.decision in ("review", "block"):
            for reason in outcome.reasons:
                s.caught_by[reason["text"]] += 1
        if outcome.decision == "block":
            s.strikes += 1
            self._event(s, "block", self.t(s, "block", amount=amount, to=to), score=outcome.score,
                        reasons=outcome.reasons)
        elif outcome.status == "FAILED_FUNDS":
            self._event(s, "fail", self.t(s, "no_funds", amount=amount), score=outcome.score)
        elif outcome.status == "SUCCESS":
            s.stolen += amount
            self._event(s, "approve", self.t(s, "approve", amount=amount, to=to), score=outcome.score,
                        reasons=outcome.reasons)

    # -- starting a mission --------------------------------------------------------------------
    def fresh_network(self) -> Network:
        """A private copy of the network for one game (about a second for 3,000 people)."""
        return copy.deepcopy(self.base)

    def start(self, mission: str, lang: str = "en", player: str = "anonymous", entry: str = "pin",
              net: Network | None = None) -> Session:
        if mission not in self.leaderboard:
            raise GameError(f"unknown mission: {mission}")
        if lang not in TEXT:
            raise GameError("lang must be en or fr")
        if entry not in ("pin", "sim"):
            raise GameError("entry must be pin or sim")
        sid = secrets.token_hex(6)
        net = net or self.fresh_network()
        now = net.now = net.now + 1
        rng = random.Random(self.rng.randrange(2**32))
        if mission == "takeover":
            hours = 36 if entry == "sim" else 5 * 24
            s = Session(sid, net, rng, mission, lang, player, now, now + hours * HOUR, max_strikes=2,
                        end_text_key="sim_back" if entry == "sim" else "owner_noticed")
            s.victim = self._pick_customer(s, min_balance=60_000, needs_contacts=True)
            s.victim_name = s.rng.choice(NAMES)
            s.attacker_device = f"D-player-{sid}"
            s.net.account_event(s.victim, "SIM_SWAP" if entry == "sim" else "PIN_RESET", s.attacker_device, now)
            deadline = s.net.timestamp(s.deadline_t)[:16].replace("T", " ")
            self._event(s, "brief", self.t(s, "takeover_brief", name=s.victim_name, balance=s.net.balance[s.victim],
                                           deadline=deadline, how=self.t(s, f"how_{entry}")))
            self._open(s, rented=False)
        elif mission == "rogue_agent":
            s = Session(sid, net, rng, mission, lang, player, now, now + 3 * DAY, max_strikes=3, end_text_key="time_up")
            s.agent = s.rng.choice(self.agents)
            self._event(s, "brief", self.t(s, "rogue_brief", agent=s.agent, region=s.net.region.get(s.agent)))
        elif mission == "wrong_transfer":
            s = Session(sid, net, rng, mission, lang, player, now, now + 3 * DAY, max_strikes=3, end_text_key="time_up")
            self._event(s, "brief", self.t(s, "wrong_brief"))
            self._open(s, rented=False)
        while len(self.sessions) >= self.max_sessions:   # forget the oldest game (dicts keep insertion order)
            del self.sessions[next(iter(self.sessions))]
        self.sessions[sid] = s
        return s

    def get(self, sid: str) -> Session:
        if sid not in self.sessions:
            raise GameError("unknown game session", status=404)
        return self.sessions[sid]

    # -- actions shared by all missions --------------------------------------------------------
    def wait(self, s: Session, duration: str) -> None:
        self._require_open(s)
        if duration not in WAITS:
            raise GameError(f"duration must be one of {list(WAITS)}")
        self._event(s, "info", self.t(s, "wait", what=WAIT_LABEL[s.lang][duration]))
        self._advance(s, WAITS[duration])

    def quit(self, s: Session) -> None:
        self._require_open(s)
        self._finish(s, "quit")

    def open_account(self, s: Session, rented: bool) -> str:
        self._require_open(s)
        if s.mission == "rogue_agent":
            raise GameError("an agent collects at their own till: no receiving accounts in this mission")
        if len(s.owned) >= 6:
            raise GameError("you already control 6 accounts")
        return self._open(s, rented)

    # -- mission: account takeover -------------------------------------------------------------
    def airtime(self, s: Session, amount: float) -> None:
        self._require_open(s, "takeover")
        t = self._advance(s, s.rng.randint(1, 5) * MINUTE)
        if t < 0:
            return
        outcome = process(s.net, self.model, type_="AIRTIME", channel="USSD", sender=s.victim,
                          receiver=self.airtime_merchant, amount=amount, device=s.attacker_device, t=t, lang=s.lang)
        if outcome.status == "SUCCESS":
            self._event(s, "info", self.t(s, "airtime", amount=amount))
        else:
            self._event(s, "fail", self.t(s, "no_funds", amount=amount))

    def steal(self, s: Session, to: str, amount: float) -> None:
        self._require_open(s, "takeover")
        if to not in s.owned:
            raise GameError("you can only send to accounts you control")
        t = self._advance(s, s.rng.randint(1, 3) * MINUTE)
        if t < 0:
            return
        outcome = process(s.net, self.model, type_="TRANSFER", channel="USSD", sender=s.victim, receiver=to,
                          amount=amount, device=s.attacker_device, t=t, lang=s.lang)
        self._scored(s, outcome, amount, to, {"type": "steal", "to_rented": to in s.rented, "amount": amount})
        if outcome.decision == "block":
            self._event(s, "info", self.t(s, "frozen"))
            self._finish(s, "caught")
        elif outcome.decision == "review":
            s.strikes += 1
            self._event(s, "review", self.t(s, "review_takeover", amount=amount), score=outcome.score,
                        reasons=outcome.reasons)
            if s.strikes >= s.max_strikes:
                self._event(s, "info", self.t(s, "frozen"))
                self._finish(s, "caught")

    # -- mission: rogue agent ------------------------------------------------------------------
    def requests(self, s: Session, count: int, amount: str, targets: str, spread: str) -> dict:
        self._require_open(s, "rogue_agent")
        if count not in (10, 30, 100) or amount not in ("5000", "25000", "varied") or \
                targets not in ("local", "national") or spread not in WAITS:
            raise GameError("count must be 10, 30 or 100; amount 5000, 25000 or varied; targets local or "
                            f"national; spread one of {list(WAITS)}")
        region = s.net.region.get(s.agent) if targets == "local" else None
        gap = WAITS[spread] / count
        summary = Counter()
        for _ in range(count):
            t = self._advance(s, max(1, int(gap * s.rng.uniform(0.5, 1.5))))
            if t < 0:
                break
            target = self._pick_customer(s, region=region, exclude={s.agent})
            value = float(amount) if amount != "varied" else float(s.rng.randrange(2, 41) * 500)
            summary["sent"] += 1
            approves = s.rng.random() < (0.07 if value <= 10_000 else 0.05)
            if not approves:
                process(s.net, self.model, type_="CASH_OUT", channel="AGENT_REQUEST", sender=target,
                        receiver=s.agent, amount=value, device=s.net.device.get(target), t=t,
                        customer_declined=True)
                summary["declined"] += 1
                continue
            summary["approved"] += 1
            outcome = process(s.net, self.model, type_="CASH_OUT", channel="AGENT_REQUEST", sender=target,
                              receiver=s.agent, amount=value, device=s.net.device.get(target), t=t, lang=s.lang)
            action = {"type": "request", "count": count, "amount": amount, "targets": targets, "spread": spread}
            self._scored(s, outcome, value, s.agent, action)
            if outcome.decision == "review":
                self._event(s, "review", self.t(s, "review_request"), score=outcome.score, reasons=outcome.reasons)
            if s.strikes >= s.max_strikes:
                self._event(s, "info", self.t(s, "suspended"))
                self._finish(s, "caught")
                break
        self._event(s, "info", self.t(s, "batch", sent=summary["sent"], declined=summary["declined"],
                                      approved=summary["approved"]))
        return dict(summary)

    # -- mission: "sent by mistake" ------------------------------------------------------------
    def call(self, s: Session, amount: float, number: str) -> None:
        self._require_open(s, "wrong_transfer")
        if number not in s.owned:
            raise GameError("you can only use numbers you control")
        if number in s.burned:
            raise GameError("this number has been flagged: open or rent another one")
        t = self._advance(s, s.rng.randint(5, 20) * MINUTE)
        if t < 0:
            return
        victim = self._pick_customer(s, min_balance=amount * 1.01, exclude=s.called | set(s.owned))
        s.called.add(victim)
        name = s.rng.choice(NAMES)
        believes = s.rng.random() < (0.4 if amount <= 5_000 else 0.3 if amount <= 15_000 else 0.2)
        if not believes:
            self._event(s, "info", self.t(s, "hung_up", name=name))
            return
        self._event(s, "info", self.t(s, "believes", name=name, amount=amount))
        device = s.net.device.get(victim)
        outcome = process(s.net, self.model, type_="TRANSFER", channel="USSD", sender=victim, receiver=number,
                          amount=amount, device=device, t=t, lang=s.lang)
        action = {"type": "call", "amount": amount, "number_rented": number in s.rented}
        if outcome.decision == "review":
            # The victim sees CleverPay's warning: most cancel, some send anyway
            s.attempts += 1
            self._log_attempt(s, outcome, action)
            for reason in outcome.reasons:
                s.caught_by[reason["text"]] += 1
            if s.rng.random() < 0.7:
                self._event(s, "review", self.t(s, "review_victim_cancels"), score=outcome.score,
                            reasons=outcome.reasons)
                return
            self._event(s, "review", self.t(s, "review_victim_sends"), score=outcome.score, reasons=outcome.reasons)
            outcome = process(s.net, self.model, type_="TRANSFER", channel="USSD", sender=victim,
                              receiver=number, amount=amount, device=device, t=t + 30, lang=s.lang,
                              override_review=True)
            if outcome.status == "SUCCESS":
                s.stolen += amount
                self._event(s, "approve", self.t(s, "approve", amount=amount, to=number), score=outcome.score)
            return
        self._scored(s, outcome, amount, number, action)
        if outcome.decision == "block":
            s.burned.add(number)
            self._event(s, "info", self.t(s, "burned", number=number))
            if s.strikes >= s.max_strikes:
                self._event(s, "info", self.t(s, "suspended"))
                self._finish(s, "caught")

    # -- views -----------------------------------------------------------------------------------
    def view(self, s: Session) -> dict:
        tips = {"takeover": "tips_takeover", "rogue_agent": "tips_rogue", "wrong_transfer": "tips_wrong"}[s.mission]
        return {
            "id": s.id, "mission": s.mission, "lang": s.lang, "player": s.player,
            "clock": s.net.timestamp(s.net.now), "deadline": s.net.timestamp(s.deadline_t),
            "hours_left": max(0.0, round((s.deadline_t - s.net.now) / HOUR, 1)),
            "stolen": round(s.stolen), "costs": round(s.costs), "profit": round(s.stolen - s.costs),
            "strikes": s.strikes, "max_strikes": s.max_strikes, "attempts": s.attempts,
            "over": s.over, "outcome": s.outcome,
            "victim": ({"account": s.victim, "name": s.victim_name, "balance": s.net.balance.get(s.victim)}
                       if s.victim else None),
            "agent": s.agent,
            "owned": [{"account": a, "balance": s.net.balance.get(a), "burned": a in s.burned,
                       "rented": a in s.rented} for a in s.owned],
            "log": s.log[-40:],
            "caught_by": s.caught_by.most_common(5),
            "tips": self.t(s, tips) if s.over else None,
            "leaderboard": self.leaderboard[s.mission],
        }
