"""HTTP endpoints for the game, and the web page that plays it.

    GET  /game                        the game (phone + fraud desk)
    POST /game/api/start              start a mission
    GET  /game/api/sessions/{id}      current state
    POST /game/api/sessions/{id}      play one action
    GET  /game/api/leaderboard        best runs per mission
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from momofraud.serving.game import Game

STATIC = Path(__file__).parent / "static"
router = APIRouter(prefix="/game", tags=["game"])


class StartIn(BaseModel):
    mission: Literal["takeover", "rogue_agent", "wrong_transfer"]
    lang: Literal["en", "fr"] = "en"
    player: str = Field(default="anonymous", min_length=1, max_length=24)
    entry: Literal["pin", "sim"] = Field(default="pin", description="takeover only: how you got in")


class ActionIn(BaseModel):
    action: Literal["wait", "open", "rent", "airtime", "steal", "requests", "call", "quit"]
    duration: Literal["10m", "2h", "1d"] = "2h"                # wait
    amount: float = Field(default=5000, gt=0, le=5_000_000)    # airtime, steal, call
    to: str | None = Field(default=None, max_length=32)        # steal: one of your accounts; call: your number
    count: Literal[10, 30, 100] = 30                           # requests
    request_amount: Literal["5000", "25000", "varied"] = "25000"
    targets: Literal["local", "national"] = "national"
    spread: Literal["10m", "2h", "1d"] = "2h"


def _game(request: Request) -> Game:
    return request.app.state.game


@router.get("", include_in_schema=False)
async def page():
    return FileResponse(STATIC / "game.html")


@router.get("/static/{name}", include_in_schema=False)
async def static(name: str):
    path = (STATIC / name).resolve()
    if path.parent != STATIC.resolve() or not path.is_file():
        return FileResponse(STATIC / "game.html", status_code=404)
    return FileResponse(path)


@router.post("/api/start")
async def start(body: StartIn, request: Request):
    game = _game(request)
    # Copying the network takes about a second: do it off the event loop so the API stays responsive
    net = await asyncio.to_thread(game.fresh_network)
    session = game.start(body.mission, lang=body.lang, player=body.player, entry=body.entry, net=net)
    return game.view(session)


@router.get("/api/sessions/{sid}")
async def state(sid: str, request: Request):
    game = _game(request)
    return game.view(game.get(sid))


@router.post("/api/sessions/{sid}")
async def act(sid: str, body: ActionIn, request: Request):
    game = _game(request)
    s = game.get(sid)
    match body.action:
        case "wait":
            game.wait(s, body.duration)
        case "open" | "rent":
            game.open_account(s, rented=body.action == "rent")
        case "airtime":
            game.airtime(s, body.amount)
        case "steal":
            game.steal(s, body.to or "", body.amount)
        case "requests":
            game.requests(s, body.count, body.request_amount, body.targets, body.spread)
        case "call":
            game.call(s, body.amount, body.to or "")
        case "quit":
            game.quit(s)
    return game.view(s)


@router.get("/api/leaderboard")
async def leaderboard(request: Request):
    return _game(request).leaderboard
