import json

import pytest
from fastapi.testclient import TestClient

from momofraud.behaviour import FEATURES
from momofraud.serving.api import create_app
from momofraud.serving.game import RENT_COST, SIM_COST, Game, GameError
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network


@pytest.fixture(scope="module")
def network():
    return Network.demo(users=600, days=10, seed=3)


@pytest.fixture(scope="module")
def model():
    return FraudModel()


@pytest.fixture
def game(network, model, tmp_path):
    return Game(network, model, log_file=tmp_path / "attempts.jsonl", seed=5)


def test_each_mission_starts_with_a_briefing(game):
    for mission in ("takeover", "rogue_agent", "wrong_transfer"):
        view = game.view(game.start(mission))
        assert view["log"][0]["kind"] == "brief"
        assert not view["over"] and view["strikes"] == 0 and view["hours_left"] > 0
    with pytest.raises(GameError):
        game.start("bank_heist")


def test_games_never_touch_the_shared_network(game, network):
    before = (network.now, network.next_id, dict(network.balance))
    s = game.start("takeover")
    game.steal(s, s.owned[0], 1000)
    game.wait(s, "1d") if not s.over else None
    assert (network.now, network.next_id, dict(network.balance)) == before
    assert s.net is not network


def test_rushing_a_takeover_gets_the_account_frozen(game):
    s = game.start("takeover")
    balance = s.net.balance[s.victim]
    game.steal(s, s.owned[0], balance * 0.9)   # whole balance, brand-new account, minutes after the PIN reset
    view = game.view(s)
    assert view["over"] and view["outcome"] == "caught"
    assert view["stolen"] == 0
    assert view["caught_by"], "a block should say why"
    assert view["tips"]
    with pytest.raises(GameError) as err:
        game.wait(s, "2h")
    assert err.value.status == 409


def test_money_only_goes_to_accounts_you_control(game):
    s = game.start("takeover")
    with pytest.raises(GameError):
        game.steal(s, game.customers[0], 1000)
    with pytest.raises(GameError):
        game.requests(s, 10, "5000", "local", "2h")   # wrong mission


def test_costs_and_profit(game):
    s = game.start("wrong_transfer")
    assert s.costs == SIM_COST
    game.open_account(s, rented=True)
    view = game.view(s)
    assert view["costs"] == SIM_COST + RENT_COST
    assert view["profit"] == view["stolen"] - view["costs"]
    assert [a["rented"] for a in view["owned"]] == [False, True]


def test_waiting_past_the_deadline_ends_the_mission(game):
    s = game.start("takeover", entry="sim")       # 36 hours
    game.wait(s, "1d")
    assert not s.over
    game.wait(s, "1d")
    assert s.over and s.outcome == "time_up"
    assert s.net.now == s.deadline_t


def test_rogue_agent_batches_are_recorded(game):
    s = game.start("rogue_agent")
    summary = game.requests(s, 30, "25000", "national", "10m")
    assert summary["sent"] == summary.get("declined", 0) + summary.get("approved", 0)
    assert summary["sent"] > 0
    # the declines are what the model sees: they land in the agent's 24-hour request history
    declined = sum(d for t, d in s.net.state.agent_requests_24h[s.agent] if t >= s.started_t)
    assert declined == summary.get("declined", 0)
    if summary.get("approved"):
        assert s.attempts > 0


def test_flagged_numbers_cannot_be_reused(game):
    s = game.start("wrong_transfer")
    number = s.owned[0]
    s.burned.add(number)
    with pytest.raises(GameError):
        game.call(s, 5000, number)
    with pytest.raises(GameError):
        game.call(s, 5000, "600000000")             # not yours


def test_scored_attempts_are_logged_with_features(game):
    s = game.start("takeover")
    game.steal(s, s.owned[0], 2000)
    rows = [json.loads(line) for line in game.log_file.read_text().splitlines()]
    assert rows and rows[-1]["session"] == s.id
    assert list(rows[-1]["features"]) == FEATURES
    assert rows[-1]["decision"] in ("approve", "review", "block")


def test_leaderboard_ranks_by_profit_and_keeps_ten(game):
    for i in range(12):
        s = game.start("wrong_transfer", player=f"p{i}")
        s.stolen = i * 1000
        game.quit(s)
    board = game.leaderboard["wrong_transfer"]
    assert len(board) == 10
    assert [r["profit"] for r in board] == sorted((r["profit"] for r in board), reverse=True)


def test_old_sessions_are_forgotten(network, model):
    g = Game(network, model, max_sessions=2, seed=1)
    first = g.start("rogue_agent")
    g.start("rogue_agent")
    g.start("rogue_agent")
    with pytest.raises(GameError) as err:
        g.get(first.id)
    assert err.value.status == 404


def test_french_narration(game):
    view = game.view(game.start("rogue_agent", lang="fr"))
    assert "Vous êtes l'agent" in view["log"][0]["text"]
    s = game.start("wrong_transfer", lang="fr")
    game.open_account(s, rented=True)
    assert "10\u202f000 FCFA" in s.log[-1]["text"]      # French thousands separator


# -- over HTTP ---------------------------------------------------------------------------------

@pytest.fixture
def client(network, model):
    with TestClient(create_app(network=network, model=model, game_log=None)) as c:
        yield c


def test_game_page_shows_the_fictional_brand_notice(client):
    page = client.get("/game")
    assert page.status_code == 200
    assert "fictional brand" in page.text and "marque fictive" in page.text
    assert client.get("/game/static/../api.py").status_code == 404


def test_play_over_http(client):
    view = client.post("/game/api/start", json={"mission": "wrong_transfer", "player": "len"}).json()
    sid = view["id"]
    view = client.post(f"/game/api/sessions/{sid}", json={"action": "rent"}).json()
    assert len(view["owned"]) == 2
    view = client.post(f"/game/api/sessions/{sid}",
                       json={"action": "call", "amount": 5000, "to": view["owned"][1]["account"]}).json()
    assert client.get(f"/game/api/sessions/{sid}").json()["log"] == view["log"]
    view = client.post(f"/game/api/sessions/{sid}", json={"action": "quit"}).json()
    assert view["over"] and view["outcome"] == "quit"
    assert client.post(f"/game/api/sessions/{sid}", json={"action": "wait"}).status_code == 409
    assert client.get("/game/api/sessions/nope").status_code == 404
    assert client.get("/game/api/leaderboard").json()["wrong_transfer"][0]["player"] == "len"
    assert client.post("/game/api/start", json={"mission": "heist"}).status_code == 422


def test_strategy_report_runs(network, model):
    from momofraud.serving.strategies import run, to_markdown

    results = run(network, model, games=1)
    assert set(results) and all(0 <= r["caught_rate"] <= 1 for r in results.values())
    assert results["takeover: rush"]["caught_rate"] == 1.0     # emptying the account at once never works
    assert "| Strategy |" in to_markdown(results)
