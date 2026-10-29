"""Fraud scoring API.

    uvicorn momofraud.serving.api:app            # http://127.0.0.1:8000/docs

Main endpoint: POST /v1/transactions scores a transfer or withdrawal against the
network's history, decides (approve / review / block), explains flagged decisions in
plain English or French, and applies the outcome. POST /v1/score does the same without
changing anything. GET /v1/monitoring compares recent traffic with the model's reference
traffic (drift).

Decisions
- approve: the money moves.
- review:  the transaction is held (in a real system: a warning and a confirmation step).
           Resubmit with "override_review": true to send it anyway, as a customer who
           confirms would.
- block:   the transaction is stopped.

Explanations (exact SHAP values) cost about 4 ms, so they are computed for review and
block decisions, or when the request sets "explain": true. Approvals stay fast.

The game (play the fraudster against this model) is served at /game.

Configuration (environment variables): MOMO_DEMO_USERS (3000), MOMO_DEMO_DAYS (30),
MOMO_DEMO_SEED (7): the size of the simulated network replayed at start-up.
MOMO_GAME_LOG (data/game/attempts.jsonl; "off" to disable): where scored game attempts are logged.
"""

from __future__ import annotations

import copy
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from momofraud.monitoring import REFERENCE_FILE, DriftMonitor, Reference
from momofraud.paths import ROOT
from momofraud.serving import gameapi
from momofraud.serving.game import Game
from momofraud.serving.model import FraudModel
from momofraud.serving.network import Network, NetworkError
from momofraud.serving.service import new_number, process
from momofraud.sim.config import REGIONS

TxType = Literal["TRANSFER", "CASH_OUT", "CASH_IN", "PAYMENT", "AIRTIME", "BILL"]
Channel = Literal["USSD", "APP", "AGENT", "AGENT_REQUEST"]
Region = Literal[tuple(REGIONS)]  # type: ignore[valid-type]


# -- schemas ---------------------------------------------------------------------------------

class TransactionIn(BaseModel):
    type: TxType
    sender: str = Field(min_length=1, max_length=32)
    receiver: str = Field(min_length=1, max_length=32)
    amount: float = Field(gt=0, le=50_000_000, description="FCFA")
    channel: Channel = "USSD"
    device: str | None = Field(default=None, max_length=64, description="the phone the request comes from")
    timestamp: datetime | None = Field(default=None, description="defaults to one second after the last event")
    customer_declined: bool = Field(default=False, description="the customer refused an agent's withdrawal request")
    override_review: bool = Field(default=False, description="send anyway after a review decision")
    explain: bool = Field(default=False, description="explain even if approved")
    lang: Literal["en", "fr"] = "en"

    model_config = {"json_schema_extra": {"examples": [{
        "type": "TRANSFER", "sender": "600000000", "receiver": "600007919", "amount": 25000,
        "channel": "USSD", "device": "D000001", "lang": "en"}]}}


class Reason(BaseModel):
    feature: str
    text: str
    contribution: float = Field(description="SHAP value, log-odds")


class Contribution(BaseModel):
    feature: str
    value: float
    contribution: float


class TransactionOut(BaseModel):
    transaction_id: int | None
    timestamp: str
    decision: Literal["approve", "review", "block", "not_scored", "declined_by_customer"]
    status: Literal["SUCCESS", "FAILED_FUNDS", "BLOCKED", "HELD_FOR_REVIEW", "DECLINED", "NOT_COMMITTED"]
    score: float | None = Field(description="probability of fraud")
    reasons: list[Reason] = []
    contributions: list[Contribution] = Field(default=[], description="largest SHAP values, both directions")
    sender_balance: float | None = None
    timings_us: dict[str, float]


class AccountIn(BaseModel):
    account: str | None = Field(default=None, min_length=1, max_length=32, description="generated if omitted")
    kind: Literal["customer", "agent"] = "customer"
    region: Region = "Douala"
    timestamp: datetime | None = None


class EventIn(BaseModel):
    account: str = Field(min_length=1, max_length=32)
    event: Literal["SIM_SWAP", "PIN_RESET", "DEVICE_CHANGE"]
    device: str | None = Field(default=None, max_length=64)
    timestamp: datetime | None = None


# -- app -------------------------------------------------------------------------------------

def _game_log() -> Path | None:
    value = os.getenv("MOMO_GAME_LOG", str(ROOT / "data" / "game" / "attempts.jsonl"))
    return None if value.lower() == "off" else Path(value)


def create_app(network: Network | None = None, model: FraudModel | None = None,
               game_log: Path | None | Literal["env"] = "env") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model = model or FraudModel()
        app.state.network = network or Network.demo(
            users=int(os.getenv("MOMO_DEMO_USERS", "3000")),
            days=int(os.getenv("MOMO_DEMO_DAYS", "30")),
            seed=int(os.getenv("MOMO_DEMO_SEED", "7")),
        )
        app.state.monitor = (DriftMonitor(Reference.load(), app.state.model.review, app.state.model.block)
                             if REFERENCE_FILE.exists() else None)
        # The game plays in copies of the network as it was at start-up, never in the API's own
        app.state.game = Game(copy.deepcopy(app.state.network), app.state.model,
                              log_file=_game_log() if game_log == "env" else game_log)
        yield

    app = FastAPI(title="MoMo fraud scoring API", version="1.0.0", lifespan=lifespan,
                  description=__doc__.split("Configuration")[0])

    app.include_router(gameapi.router)

    @app.exception_handler(NetworkError)
    async def network_error(_: Request, exc: NetworkError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    # Endpoints are `async def` on purpose: they run one at a time on the event loop, so the
    # network state is never modified by two requests at once. Each takes well under a
    # millisecond (more when explaining), which a single process handles comfortably.

    @app.get("/health")
    async def health(request: Request):
        net: Network = request.app.state.network
        return {"status": "ok", "accounts": len(net.kind), "now": net.timestamp(net.now)}

    @app.get("/v1/model")
    async def model_info(request: Request):
        meta = request.app.state.model.metadata
        return {k: meta[k] for k in ("model", "created", "thresholds", "threshold_rule", "test_adaptive_world")}

    @app.get("/v1/monitoring")
    async def monitoring(request: Request):
        """Drift of the last scored transactions against the model's reference traffic."""
        monitor: DriftMonitor | None = request.app.state.monitor
        if monitor is None:
            return JSONResponse(status_code=503, content={"detail": "no drift reference: run "
                                                          "`python -m momofraud.monitoring reference`"})
        return monitor.report()

    @app.post("/v1/transactions", response_model=TransactionOut)
    async def transactions(tx: TransactionIn, request: Request):
        return _handle(request, tx, commit=True)

    @app.post("/v1/score", response_model=TransactionOut)
    async def score(tx: TransactionIn, request: Request):
        return _handle(request, tx, commit=False)

    @app.post("/v1/accounts", status_code=201)
    async def open_account(body: AccountIn, request: Request):
        net: Network = request.app.state.network
        t = net.to_seconds(body.timestamp)
        account = body.account or new_number(net)
        net.open_account(account, body.kind, body.region, t)
        return _account_view(net, account)

    @app.get("/v1/accounts")
    async def list_accounts(request: Request, kind: Literal["customer", "agent", "merchant"] = "customer",
                            limit: int = Query(20, ge=1, le=200), region: Region | None = None):
        net: Network = request.app.state.network
        found = [a for a, k in net.kind.items() if k == kind and (region is None or net.region.get(a) == region)]
        return [{"account": a, "region": net.region.get(a), "balance": net.balance.get(a)} for a in found[:limit]]

    @app.get("/v1/accounts/{account}")
    async def account(account: str, request: Request):
        net: Network = request.app.state.network
        net.require(account, "requested")
        return _account_view(net, account)

    @app.post("/v1/events")
    async def event(body: EventIn, request: Request):
        net: Network = request.app.state.network
        t = net.to_seconds(body.timestamp)
        net.account_event(body.account, body.event, body.device, t)
        return {"account": body.account, "event": body.event, "timestamp": net.timestamp(t)}

    return app


def _handle(request: Request, tx: TransactionIn, commit: bool) -> TransactionOut:
    net: Network = request.app.state.network
    outcome = process(
        net, request.app.state.model, type_=tx.type, channel=tx.channel, sender=tx.sender,
        receiver=tx.receiver, amount=tx.amount, device=tx.device, t=net.to_seconds(tx.timestamp),
        customer_declined=tx.customer_declined, override_review=tx.override_review, explain=tx.explain,
        lang=tx.lang, commit=commit)
    monitor = request.app.state.monitor
    if commit and monitor is not None and outcome.features is not None:
        monitor.update(outcome.features, outcome.score)
    return TransactionOut(**outcome.public())


def _account_view(net: Network, account: str) -> dict:
    opened = net.state.opened_t.get(account)
    return {
        "account": account, "kind": net.kind[account], "region": net.region.get(account),
        "balance": net.balance.get(account), "device": net.device.get(account),
        "opened": net.timestamp(opened) if opened is not None else None,
        "recent": list(net.recent.get(account, []))[-10:],
    }


app = create_app()
