"""Scripted players: which strategies beat the model, and which get caught?

    python -m momofraud.serving.strategies     # writes reports/game_strategies.md and .json

Each strategy is played several times on the demo network (a fresh copy every game, different
random seeds) through exactly the same game engine as the web page. A strategy that wins
reliably is a blind spot of the model, and the place to look first when retraining.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np

from momofraud.paths import REPORTS_DIR
from momofraud.serving.game import Game, Session
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network

GAMES_PER_STRATEGY = 6
Play = Callable[[Game, Session], None]


def _until_over(game: Game, s: Session, step: Callable[[], None], limit: int = 60) -> None:
    for _ in range(limit):
        if s.over:
            return
        step()
    if not s.over:
        game.quit(s)


def _wait(game: Game, s: Session, duration: str) -> None:
    if not s.over:
        game.wait(s, duration)


# -- account takeover ----------------------------------------------------------------------------

def takeover_rush(game: Game, s: Session) -> None:
    """Send the whole balance to a new number straight away."""
    game.steal(s, s.owned[0], int(s.net.balance[s.victim] / 1.002))
    if not s.over:
        game.quit(s)


def takeover_quick_small(game: Game, s: Session) -> None:
    """Small amounts to a new number, straight away, every 10 minutes."""
    def step():
        game.steal(s, s.owned[0], 5000)
        _wait(game, s, "10m")
    _until_over(game, s, step, limit=20)


def takeover_patient_new_number(game: Game, s: Session) -> None:
    """Wait three days, then small amounts to the new number."""
    for _ in range(3):
        _wait(game, s, "1d")
    def step():
        game.steal(s, s.owned[0], 5000)
        _wait(game, s, "2h")
    _until_over(game, s, step, limit=20)


def takeover_patient_rented(game: Game, s: Session) -> None:
    """Wait three days, rent an aged account, then small amounts to it."""
    for _ in range(3):
        _wait(game, s, "1d")
    if not s.over:
        game.open_account(s, rented=True)
    def step():
        game.steal(s, s.owned[-1], 5000)
        _wait(game, s, "2h")
    _until_over(game, s, step, limit=20)


# -- rogue agent ---------------------------------------------------------------------------------

def rogue_blitz(game: Game, s: Session) -> None:
    """100 requests of 25,000 to the whole country in 10 minutes, again and again."""
    _until_over(game, s, lambda: game.requests(s, 100, "25000", "national", "10m"), limit=10)


def rogue_slow_local(game: Game, s: Session) -> None:
    """10 requests of varied small amounts to the agent's own town, spread over a day."""
    _until_over(game, s, lambda: game.requests(s, 10, "varied", "local", "1d"), limit=10)


# -- "sent by mistake" ---------------------------------------------------------------------------

def _caller(rented: bool) -> Play:
    def play(game: Game, s: Session) -> None:
        def step():
            number = next((a for a in s.owned if a not in s.burned and (a in s.rented) == rented), None)
            if number is None:
                number = game.open_account(s, rented=rented) if len(s.owned) < 6 else None
            if number is None:
                game.quit(s)
                return
            game.call(s, 5000, number)
            _wait(game, s, "2h")
        _until_over(game, s, step, limit=40)
    return play


STRATEGIES: dict[str, tuple[str, dict, Play]] = {
    "takeover: rush": ("takeover", {}, takeover_rush),
    "takeover: small amounts, straight away": ("takeover", {}, takeover_quick_small),
    "takeover: wait 3 days, new number": ("takeover", {}, takeover_patient_new_number),
    "takeover: wait 3 days, rented account": ("takeover", {}, takeover_patient_rented),
    "rogue agent: 100 requests in 10 min": ("rogue_agent", {}, rogue_blitz),
    "rogue agent: 10 local requests a day": ("rogue_agent", {}, rogue_slow_local),
    "sent by mistake: fresh numbers": ("wrong_transfer", {}, _caller(rented=False)),
    "sent by mistake: rented numbers": ("wrong_transfer", {}, _caller(rented=True)),
}


def run(network: Network | None = None, model: FraudModel | None = None, games: int = GAMES_PER_STRATEGY,
        seed: int = 0) -> dict:
    game = Game(network or Network.demo(), model or FraudModel(), seed=seed, max_sessions=2)
    results = {}
    for name, (mission, options, play) in STRATEGIES.items():
        runs = []
        for _ in range(games):
            s = game.start(mission, **options)
            play(game, s)
            runs.append({"profit": s.stolen - s.costs, "stolen": s.stolen, "caught": s.outcome == "caught",
                         "attempts": s.attempts, "flags": sum(s.caught_by.values()) > 0})
        results[name] = {
            "games": games,
            "mean_profit": float(np.mean([r["profit"] for r in runs])),
            "caught_rate": float(np.mean([r["caught"] for r in runs])),
            "mean_attempts": float(np.mean([r["attempts"] for r in runs])),
            "never_flagged_rate": float(np.mean([not r["flags"] for r in runs])),
        }
        print(f"{name:<42} profit {results[name]['mean_profit']:>9,.0f}  caught {results[name]['caught_rate']:.0%}")
    return results


def to_markdown(results: dict) -> str:
    lines = [
        "# Game strategies against the model",
        "",
        "Generated by `python -m momofraud.serving.strategies`. Each scripted strategy is played",
        f"{next(iter(results.values()))['games']} times on the demo network, through the same game engine as the",
        "web page.",
        "Profit is what reached the player's accounts minus the cost of numbers (500 FCFA new, 10,000 rented).",
        "",
        "| Strategy | Mean profit (FCFA) | Caught | Never flagged | Scored attempts |",
        "|---|---|---|---|---|",
    ]
    for name, r in results.items():
        lines.append(f"| {name} | {r['mean_profit']:,.0f} | {r['caught_rate']:.0%} | {r['never_flagged_rate']:.0%} | "
                     f"{r['mean_attempts']:.1f} |")
    lines += [
        "",
        "\"Never flagged\" means not a single review or block in the whole game: the model did not see",
        "the scam at all. Those strategies are its blind spots.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    report = run()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "game_strategies.json").write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "game_strategies.md").write_text(to_markdown(report), encoding="utf-8")
    print((REPORTS_DIR / "game_strategies.md").read_text(encoding="utf-8"))
