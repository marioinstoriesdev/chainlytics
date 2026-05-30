"""
hackathon/src/executor.py
Signal-to-Silent-Execution loop.

Polls Chainlytics for TOON scores on the configured watchlist.
When a BUY signal clears the threshold the pipeline executes:

  1. GET /v1/vanish/one-time-wallet          -- fresh disposable signer
  2. Jupiter v6 build_private_swap()         -- unsigned swap tx (OTW as signer)
  3. POST /v1/vanish/trade                   -- Chainlytics proxies to Vanish
  4. POST /v1/vanish/commit (polled)         -- wait for terminal status

SELL path:
  1. GET /v1/vanish/balance                  -- confirm token balance
  2. GET /v1/vanish/one-time-wallet
  3. Jupiter build_private_swap() (token -> SOL)
  4. POST /v1/vanish/trade
  5. POST /v1/vanish/commit (polled)

All thresholds, amounts, and intervals come from config.py.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config
from .chainlytics_client import ChainalyticsClient, TOONScore
from .jupiter_client import JupiterClient, SOL_MINT
from .vanish_client import VanishClient, SOL_NATIVE_MINT

_BUY_ACTIONS  = {"BUY", "BUY_SCALED"}
_SELL_ACTIONS = {"SELL"}

logger = logging.getLogger("executor")


@dataclass
class TradeRecord:
    token_address:   str
    action:          str
    decision_score:  float
    confidence:      float
    regime:          str
    insider_risk:    str
    amount_lamports: int
    one_time_wallet: str
    vanish_tx_id:    str
    jito_bundle_id:  Optional[str]
    status:          str
    vanish_fee:      Optional[str]
    balance_changes: List[Dict[str, Any]]
    solscan_url:     str
    started_at:      float
    settled_at:      Optional[float]
    error:           Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address":   self.token_address,
            "action":          self.action,
            "decision_score":  self.decision_score,
            "confidence":      self.confidence,
            "regime":          self.regime,
            "insider_risk":    self.insider_risk,
            "amount_lamports": self.amount_lamports,
            "one_time_wallet": self.one_time_wallet,
            "vanish_tx_id":    self.vanish_tx_id,
            "jito_bundle_id":  self.jito_bundle_id,
            "status":          self.status,
            "vanish_fee":      self.vanish_fee,
            "balance_changes": self.balance_changes,
            "solscan_url":     self.solscan_url,
            "started_at":      self.started_at,
            "settled_at":      self.settled_at,
            "error":           self.error,
        }


class Executor:
    """
    Background execution engine.
    Run via: asyncio.create_task(executor.start())
    Scores and trade_history are exposed for the dashboard API.
    """

    def __init__(self):
        self.vanish      = VanishClient()
        self.chainlytics = ChainalyticsClient()
        self.jupiter     = JupiterClient()

        self.scores:        Dict[str, TOONScore]  = {}
        self.trade_history: List[TradeRecord]     = []
        self.balances:      List[Dict[str, Any]]  = []

        self._active_trades:    int  = 0
        self._running:          bool = False
        self._tokens_in_flight: set  = set()

    async def start(self) -> None:
        self._running = True
        logger.info("Executor starting. wallet=%s", self.vanish.user_address)

        await self.vanish.recover_pending()
        await self._refresh_balances()

        watchlist = config.watchlist()
        if not watchlist:
            logger.warning("Watchlist is empty. Add token mint addresses to config.yaml.")

        logger.info(
            "Watching %d token(s). score>=%.1f conf>=%.2f",
            len(watchlist), config.min_score(), config.min_confidence(),
        )
        while self._running:
            await self._poll_cycle(watchlist)
            await asyncio.sleep(config.poll_interval_seconds())

    def stop(self) -> None:
        self._running = False

    async def _poll_cycle(self, watchlist: List[str]) -> None:
        await asyncio.gather(*[self._evaluate(addr) for addr in watchlist], return_exceptions=True)

    async def _evaluate(self, token: str) -> None:
        try:
            cached = self.scores.get(token)
            score = cached if (cached and not cached.cache_expired) else await self.chainlytics.score(token)
            self.scores[token] = score

            if score.error:
                return

            is_buy  = score.action in _BUY_ACTIONS  and score.passes_threshold()
            is_sell = score.action in _SELL_ACTIONS and score.passes_threshold()

            if not is_buy and not is_sell:
                logger.debug("%s... score=%.1f action=%s conf=%.2f -- no signal",
                             token[:12], score.decision_score, score.action, score.confidence)
                return

            if token in self._tokens_in_flight:
                return

            if self._active_trades >= config.max_concurrent_trades():
                logger.warning("Max concurrent trades reached, skipping %s...", token[:12])
                return

            logger.info("%s SIGNAL: %s... score=%.2f conf=%.2f regime=%s",
                        score.action, token[:12], score.decision_score, score.confidence, score.regime)

            if is_sell:
                asyncio.create_task(self._execute_sell(score))
            else:
                asyncio.create_task(self._execute_trade(score))

        except Exception as e:
            logger.error("Evaluate error %s...: %s", token[:12], e, exc_info=True)

    async def _execute_trade(self, score: TOONScore) -> None:
        token = score.token_address
        self._tokens_in_flight.add(token)
        self._active_trades += 1
        started = time.time()

        record = TradeRecord(
            token_address=token, action=score.action,
            decision_score=score.decision_score, confidence=score.confidence,
            regime=score.regime, insider_risk=score.insider_risk,
            amount_lamports=config.trade_amount_lamports(),
            one_time_wallet="", vanish_tx_id="", jito_bundle_id=None,
            status="starting", vanish_fee=None, balance_changes=[],
            solscan_url="", started_at=started, settled_at=None, error=None,
        )
        self.trade_history.insert(0, record)

        try:
            # Step 1: fresh one-time wallet
            record.status = "getting_one_time_wallet"
            otw = await self.vanish.get_one_time_wallet()
            record.one_time_wallet = otw
            logger.info("One-time wallet: %s...", otw[:12])

            # Step 2: build unsigned swap tx via Jupiter (SOL -> token)
            record.status = "building_swap_tx"
            swap_tx = await self.jupiter.build_private_swap(
                input_mint=SOL_MINT,
                output_mint=token,
                amount=config.trade_amount_lamports(),
                user_public_key=otw,
            )
            if not swap_tx:
                raise RuntimeError("Jupiter failed to build swap transaction")

            # Step 3: submit to Vanish via Chainlytics
            record.status = "submitting"
            resp = await self.vanish.create_trade(
                source_token_address=SOL_NATIVE_MINT,
                target_token_address=token,
                amount=config.trade_amount_lamports(),
                swap_transaction_b64=swap_tx,
                one_time_wallet=otw,
            )
            tx_id = resp.get("tx_id", "")
            record.vanish_tx_id   = tx_id
            record.jito_bundle_id = resp.get("jito_bundle_id")
            record.solscan_url    = f"https://solscan.io/tx/{tx_id}"
            logger.info("Trade submitted: tx=%s... jito=%s", tx_id[:12], record.jito_bundle_id or "n/a")

            # Step 4: commit
            record.status = "waiting_for_settlement"
            commit = await self.vanish.commit(tx_id)
            record.status          = commit.get("status", "unknown")
            record.vanish_fee      = commit.get("vanish_fee")
            record.balance_changes = commit.get("balance_changes", [])
            record.settled_at      = time.time()
            logger.info("Trade complete: %s... status=%s explorer=%s", token[:12], record.status, record.solscan_url)
            await self._refresh_balances()

        except Exception as e:
            record.status     = "error"
            record.error      = str(e)
            record.settled_at = time.time()
            logger.error("Trade error %s...: %s", token[:12], e, exc_info=True)
        finally:
            self._tokens_in_flight.discard(token)
            self._active_trades -= 1

    async def _execute_sell(self, score: TOONScore) -> None:
        token = score.token_address
        self._tokens_in_flight.add(token)
        self._active_trades += 1
        started = time.time()

        record = TradeRecord(
            token_address=token, action=score.action,
            decision_score=score.decision_score, confidence=score.confidence,
            regime=score.regime, insider_risk=score.insider_risk,
            amount_lamports=0, one_time_wallet="", vanish_tx_id="",
            jito_bundle_id=None, status="starting_sell", vanish_fee=None,
            balance_changes=[], solscan_url="", started_at=started, settled_at=None, error=None,
        )
        self.trade_history.insert(0, record)

        try:
            record.status = "checking_balance"
            balances = await self.vanish.get_balances()
            token_balance = next(
                (int(b["balance"]) for b in balances
                 if b.get("token_address") == token and int(b.get("balance", 0)) > 0),
                0,
            )
            if token_balance == 0:
                record.status    = "skipped_no_balance"
                record.error     = "No token balance in Vanish account"
                record.settled_at = time.time()
                logger.info("SELL skipped: no %s... balance", token[:12])
                return

            record.amount_lamports = token_balance

            record.status = "getting_one_time_wallet"
            otw = await self.vanish.get_one_time_wallet()
            record.one_time_wallet = otw

            # Build unsigned swap tx via Jupiter (token -> SOL)
            record.status = "building_swap_tx"
            swap_tx = await self.jupiter.build_private_swap(
                input_mint=token,
                output_mint=SOL_MINT,
                amount=token_balance,
                user_public_key=otw,
            )
            if not swap_tx:
                raise RuntimeError("Jupiter failed to build sell swap transaction")

            record.status = "submitting"
            resp = await self.vanish.create_trade(
                source_token_address=token,
                target_token_address=SOL_NATIVE_MINT,
                amount=token_balance,
                swap_transaction_b64=swap_tx,
                one_time_wallet=otw,
            )
            tx_id = resp.get("tx_id", "")
            record.vanish_tx_id   = tx_id
            record.jito_bundle_id = resp.get("jito_bundle_id")
            record.solscan_url    = f"https://solscan.io/tx/{tx_id}"
            logger.info("Sell submitted: tx=%s... jito=%s", tx_id[:12], record.jito_bundle_id or "n/a")

            record.status = "waiting_for_settlement"
            commit = await self.vanish.commit(tx_id)
            record.status          = commit.get("status", "unknown")
            record.vanish_fee      = commit.get("vanish_fee")
            record.balance_changes = commit.get("balance_changes", [])
            record.settled_at      = time.time()
            logger.info("Sell complete: %s... status=%s", token[:12], record.status)
            await self._refresh_balances()

        except Exception as e:
            record.status     = "error"
            record.error      = str(e)
            record.settled_at = time.time()
            logger.error("Sell error %s...: %s", token[:12], e, exc_info=True)
        finally:
            self._tokens_in_flight.discard(token)
            self._active_trades -= 1

    async def _refresh_balances(self) -> None:
        try:
            self.balances = await self.vanish.get_balances()
        except Exception as e:
            logger.warning("Balance refresh failed: %s", e)

    # Dashboard accessors
    def get_scores_dict(self)  -> Dict[str, Any]: return {a: s.to_dict() for a, s in self.scores.items()}
    def get_trades_list(self)  -> List[Dict]:     return [t.to_dict() for t in self.trade_history[:50]]
    def get_balances_list(self) -> List[Dict]:    return self.balances
    def get_status(self)        -> Dict[str, Any]:
        return {
            "running":          self._running,
            "active_trades":    self._active_trades,
            "tokens_in_flight": list(self._tokens_in_flight),
            "watchlist":        config.watchlist(),
            "wallet":           self.vanish.user_address,
            "thresholds":       {"min_score": config.min_score(), "min_confidence": config.min_confidence()},
        }
