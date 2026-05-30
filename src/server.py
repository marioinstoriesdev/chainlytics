"""
hackathon/src/server.py

FastAPI backend for the Signal-to-Silent-Execution dashboard.

Starts the Executor as a background asyncio task on startup.
Serves the single-file frontend from frontend/index.html.

Endpoints:
    GET  /                      Frontend dashboard HTML
    GET  /api/status            Executor status (running, active_trades, watchlist)
    GET  /api/scores            Current Chainlytics TOON scores for all watchlist tokens
    GET  /api/trades            Recent trade history (last 50)
    GET  /api/balance           Current Vanish balance for the configured wallet
    POST /api/execute/{token}   Manually trigger execution for a token (demo helper)
    POST /api/watchlist/add     Add a token to the live watchlist
    GET  /health                Health check

All config values from config.py. Run with:
    python -m src.server
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config
from .executor import Executor

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s]: %(message)s",
)
logger = logging.getLogger("server")

FRONTEND_PATH = Path(__file__).parent.parent / "frontend" / "index.html"

app = FastAPI(
    title="Chainlytics x Vanish",
    description="Signal-to-Silent-Execution -- Solana Frontier Hackathon 2026",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

executor: Optional[Executor] = None


@app.on_event("startup")
async def startup():
    global executor
    executor = Executor()
    asyncio.create_task(executor.start())
    logger.info(f"Dashboard: http://{config.server_host()}:{config.server_port()}")


@app.on_event("shutdown")
async def shutdown():
    if executor:
        executor.stop()


# -- Frontend

@app.get("/", include_in_schema=False)
async def frontend():
    if not FRONTEND_PATH.exists():
        return JSONResponse({"error": "Frontend not found. Check frontend/index.html."}, status_code=500)
    return FileResponse(FRONTEND_PATH, media_type="text/html")


# -- API

@app.get("/health")
async def health():
    return {"status": "ok", "ts": int(time.time())}


@app.get("/api/status")
async def api_status():
    if not executor:
        raise HTTPException(503, "Executor not started")
    return executor.get_status()


@app.get("/api/scores")
async def api_scores():
    if not executor:
        raise HTTPException(503, "Executor not started")
    return executor.get_scores_dict()


@app.get("/api/trades")
async def api_trades():
    if not executor:
        raise HTTPException(503, "Executor not started")
    return executor.get_trades_list()


@app.get("/api/balance")
async def api_balance():
    if not executor:
        raise HTTPException(503, "Executor not started")
    return executor.get_balances_list()


class WatchlistAddRequest(BaseModel):
    token_address: str


@app.get("/api/deposit_address")
async def api_deposit_address(token_address: str = "11111111111111111111111111111111"):
    """
    Return the Vanish deposit address for a given token (SOL by default).
    Use this to fund the Vanish account before executing trades.
    Send SOL on-chain to the returned address, then call /commit on startup.
    """
    if not executor:
        raise HTTPException(503, "Executor not started")
    addr = await executor.vanish.get_deposit_address(token_address)
    return {
        "deposit_address": addr,
        "token_address": token_address,
        "note": "Send SOL to this address to fund your Vanish account. "
                "Your wallet address will not appear as the trade signer.",
    }


@app.post("/api/watchlist/add")
async def api_watchlist_add(req: WatchlistAddRequest):
    """
    Add a token to the live watchlist without restarting.
    The token will be scored on the next poll cycle.
    Note: this does not persist the change to config.yaml.
    """
    token = req.token_address.strip()
    if not token:
        raise HTTPException(400, "token_address is required")
    wl = config.load().setdefault("execution", {}).setdefault("watchlist", [])
    if token not in wl:
        wl.append(token)
        logger.info(f"Added to watchlist: {token[:12]}...")
    return {"ok": True, "watchlist": wl}


@app.post("/api/execute/{token_address}")
async def api_execute(token_address: str):
    """
    Manually trigger execution for a token regardless of current score.
    Useful for demos. Respects max_concurrent_trades limit.
    """
    if not executor:
        raise HTTPException(503, "Executor not started")

    token = token_address.strip()
    if not token:
        raise HTTPException(400, "token_address required")

    cached = executor.scores.get(token)
    if not cached:
        # Score it now before executing
        score = await executor.chainlytics.score(token)
        executor.scores[token] = score
    else:
        score = cached

    if score.error:
        raise HTTPException(400, f"Score error: {score.error}")

    if token in executor._tokens_in_flight:
        raise HTTPException(409, "Trade already in flight for this token")

    asyncio.create_task(executor._execute_trade(score))
    return {
        "ok": True,
        "token_address": token,
        "score": score.decision_score,
        "action": score.action,
        "confidence": score.confidence,
        "message": "Execution started. Check /api/trades for results.",
    }


def main():
    uvicorn.run(
        "src.server:app",
        host=config.server_host(),
        port=config.server_port(),
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
