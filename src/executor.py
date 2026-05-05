"""
hackathon/src/executor.py

Signal-to-Silent-Execution loop.

Polls Chainlytics for scores on the configured watchlist. When a token crosses
the buy threshold, automatically executes the trade via Vanish:

BUY / BUY_SCALED path (SOL -> token):
    1. GET Vanish /trade/one-time-wallet
    2. GET Jupiter quote (SOL -> token)
    3. POST Jupiter /v6/swap (unsigned tx with one_time_wallet as signer)
    4. POST Vanish /trade/create
    5. POST Vanish /commit (polls until terminal status)

SELL / SELL_SCALED path (token -> SOL):
    1. GET Vanish balances -- find token balance to sell
    2. GET Vanish /trade/one-time-wallet
    3. GET Jupiter quote (token -> SOL)
    4. POST Jupiter /v6/swap (unsigned tx with one_time_wallet as signer)
    5. POST Vanish /trade/create
    6. POST Vanish /commit (polls until terminal status)

Trade history and current scores are kept in memory and served by server.py
via the dashboard API.

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
from .vanish_client import VanishClient

SOL_NATIVE_MINT = "11111111111111111111111111111111"
_BUY_ACTIONS = {"BUY", "BUY_SCALED"}
_SELL_ACTIONS = {"SELL", "SELL_SCALED"}

logger = logging.getLogger("executor")


@dataclass
class TradeRecord:
    token_address: str
    action: str
    decision_score: float
    confidence: float
    regime: str
    insider_risk: str
    amount_lamports: int
    one_time_wallet: str
    vanish_tx_id: str
    jito_bundle_id: Optional[str]
    status: str
    vanish_fee: Optional[str]
    balance_changes: List[Dict[str, Any]]
    solscan_url: str
    started_at: float
    settled_at: Optional[float]
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "action": self.action,
            "decision_score": self.decision_score,
            "confidence": self.confidence,
            "regime": self.regime,
            "insider_risk": self.insider_risk,
            "amount_lamports": self.amount_lamports,
            "one_time_wallet": self.one_time_wallet,
            "vanish_tx_id": self.vanish_tx_id,
            "jito_bundle_id": self.jito_bundle_id,
            "status": self.status,
            "vanish_fee": self.vanish_fee,
            "balance_changes": self.balance_changes,
            "solscan_url": self.solscan_url,
            "started_at": self.started_at,
            "settled_at": self.settled_at,
            "error": self.error,
        }


class Executor:
    """
    Background execution engine. Run via start() as an asyncio task.
    Exposes scores and trade_history for the dashboard API.
    """

    def __init__(self):
        self.vanish = VanishClient()
        self.chainlytics = ChainalyticsClient()
        self.jupiter = JupiterClient()

        # Live state exposed to the dashboard
        self.scores: Dict[str, TOONScore] = {}
        self.trade_history: List[TradeRecord] = []
        self.balances: List[Dict[str, Any]] = []

        self._active_trades: int = 0
        self._running: bool = False
        self._tokens_in_flight: set = set()

    async def start(self) -> None:
        """
        Entry point. Call as asyncio.create_task(executor.start()).
        Runs indefinitely until self._running is set to False.
        """
        self._running = True
        logger.info("Executor starting...")

        # Recover any uncommitted transactions from prior sessions
        await self.vanish.recover_pending()

        # Initial balance snapshot
        await self._refresh_balances()

        watchlist = config.watchlist()
        if not watchlist:
            logger.warning("Watchlist is empty. Add token addresses to config.yaml.")

        logger.info(
            f"Watching {len(watchlist)} token(s). "
            f"Threshold: score>={config.min_score()} conf>={config.min_confidence()}"
        )

        while self._running:
            await self._poll_cycle(watchlist)
            await asyncio.sleep(config.poll_interval_seconds())

    def stop(self) -> None:
        self._running = False

    async def _poll_cycle(self, watchlist: List[str]) -> None:
        tasks = [self._evaluate_token(addr) for addr in watchlist]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _evaluate_token(self, token_address: str) -> None:
        try:
            cached = self.scores.get(token_address)
            if cached and not cached.cache_expired:
                score = cached
            else:
                score = await self.chainlytics.score(token_address)
                self.scores[token_address] = score

            if score.error:
                return

            is_buy = score.action in _BUY_ACTIONS and score.passes_threshold()
            is_sell = score.action in _SELL_ACTIONS and score.passes_threshold()

            if not is_buy and not is_sell:
                logger.debug(
                    f"No signal for {token_address[:12]}...: "
                    f"score={score.decision_score:.1f} action={score.action} "
                    f"conf={score.confidence:.2f}"
                )
                return

            if token_address in self._tokens_in_flight:
                logger.debug(f"Trade already in flight for {token_address[:12]}..., skipping")
                return

            if self._active_trades >= config.max_concurrent_trades():
                logger.warning(
                    f"Max concurrent trades ({config.max_concurrent_trades()}) reached. "
                    f"Skipping {token_address[:12]}..."
                )
                return

            if is_sell:
                logger.info(
                    f"SELL SIGNAL: {token_address[:12]}... "
                    f"score={score.decision_score:.2f} action={score.action} "
                    f"conf={score.confidence:.2f} regime={score.regime}"
                )
                asyncio.create_task(self._execute_sell(score))
            else:
                logger.info(
                    f"BUY SIGNAL: {token_address[:12]}... "
                    f"score={score.decision_score:.2f} action={score.action} "
                    f"conf={score.confidence:.2f} regime={score.regime}"
                )
                asyncio.create_task(self._execute_trade(score))

        except Exception as e:
            logger.error(f"Evaluate error for {token_address[:12]}...: {e}", exc_info=True)

    async def _execute_trade(self, score: TOONScore) -> None:
        token = score.token_address
        self._tokens_in_flight.add(token)
        self._active_trades += 1
        started_at = time.time()

        record = TradeRecord(
            token_address=token,
            action=score.action,
            decision_score=score.decision_score,
            confidence=score.confidence,
            regime=score.regime,
            insider_risk=score.insider_risk,
            amount_lamports=config.trade_amount_lamports(),
            one_time_wallet="",
            vanish_tx_id="",
            jito_bundle_id=None,
            status="starting",
            vanish_fee=None,
            balance_changes=[],
            solscan_url="",
            started_at=started_at,
            settled_at=None,
            error=None,
        )
        self.trade_history.insert(0, record)

        try:
            # Step 1: get one-time wallet
            record.status = "getting_one_time_wallet"
            one_time_wallet = await self.vanish.get_one_time_wallet()
            record.one_time_wallet = one_time_wallet
            logger.info(f"One-time wallet: {one_time_wallet[:12]}...")

            # Step 2: build unsigned Jupiter swap tx (SOL -> token)
            record.status = "building_swap_tx"
            swap_tx = await self.jupiter.build_private_swap(
                output_mint=token,
                amount_lamports=config.trade_amount_lamports(),
                one_time_wallet=one_time_wallet,
                input_mint=SOL_MINT,
            )
            if swap_tx is None:
                raise RuntimeError("Jupiter failed to return a swap transaction")

            # Step 3: submit to Vanish
            record.status = "submitting_to_vanish"
            trade_resp = await self.vanish.create_trade(
                source_token_address=SOL_MINT,
                target_token_address=token,
                amount=config.trade_amount_lamports(),
                swap_transaction_b64=swap_tx,
                one_time_wallet=one_time_wallet,
            )
            tx_id = trade_resp.get("tx_id", "")
            jito_bundle_id = trade_resp.get("jito_bundle_id")
            record.vanish_tx_id = tx_id
            record.jito_bundle_id = jito_bundle_id
            record.solscan_url = f"https://solscan.io/tx/{tx_id}"
            logger.info(
                f"Trade submitted: tx_id={tx_id[:12]}... "
                f"jito_bundle={jito_bundle_id or 'n/a'}"
            )

            # Step 4: commit and wait for settlement
            record.status = "waiting_for_settlement"
            commit_result = await self.vanish.commit(tx_id)

            final_status = commit_result.get("status", "unknown")
            record.status = final_status
            record.vanish_fee = commit_result.get("vanish_fee")
            record.balance_changes = commit_result.get("balance_changes", [])
            record.settled_at = time.time()

            logger.info(
                f"Trade complete: {token[:12]}... status={final_status} "
                f"tx_id={tx_id[:12]}... solscan={record.solscan_url}"
            )

            # Refresh balances after settlement
            await self._refresh_balances()

        except Exception as e:
            record.status = "error"
            record.error = str(e)
            record.settled_at = time.time()
            logger.error(f"Trade execution error for {token[:12]}...: {e}", exc_info=True)

        finally:
            self._tokens_in_flight.discard(token)
            self._active_trades -= 1

    async def _execute_sell(self, score: TOONScore) -> None:
        """
        SELL / SELL_SCALED path: swap token -> SOL via Vanish.

        Looks up the current Vanish balance for the token. If no balance is held,
        the sell is skipped (nothing to sell). Otherwise executes:
            token -> SOL via Jupiter unsigned swap -> Vanish one-time wallet.
        """
        token = score.token_address
        self._tokens_in_flight.add(token)
        self._active_trades += 1
        started_at = time.time()

        record = TradeRecord(
            token_address=token,
            action=score.action,
            decision_score=score.decision_score,
            confidence=score.confidence,
            regime=score.regime,
            insider_risk=score.insider_risk,
            amount_lamports=0,
            one_time_wallet="",
            vanish_tx_id="",
            jito_bundle_id=None,
            status="starting_sell",
            vanish_fee=None,
            balance_changes=[],
            solscan_url="",
            started_at=started_at,
            settled_at=None,
            error=None,
        )
        self.trade_history.insert(0, record)

        try:
            # Check Vanish balance for this token
            record.status = "checking_balance"
            balances = await self.vanish.get_balances()
            token_balance = next(
                (int(b["balance"]) for b in balances
                 if b.get("token_address") == token and int(b.get("balance", 0)) > 0),
                0,
            )

            if token_balance == 0:
                logger.info(
                    f"SELL skipped: no {token[:12]}... balance in Vanish account"
                )
                record.status = "skipped_no_balance"
                record.error = "No token balance available to sell"
                record.settled_at = time.time()
                return

            record.amount_lamports = token_balance
            logger.info(f"Selling {token_balance} units of {token[:12]}...")

            # Get one-time wallet
            record.status = "getting_one_time_wallet"
            one_time_wallet = await self.vanish.get_one_time_wallet()
            record.one_time_wallet = one_time_wallet

            # Build unsigned sell swap (token -> SOL)
            record.status = "building_swap_tx"
            swap_tx = await self.jupiter.build_private_swap(
                input_mint=token,
                output_mint=SOL_MINT,
                amount_lamports=token_balance,
                one_time_wallet=one_time_wallet,
            )
            if swap_tx is None:
                raise RuntimeError("Jupiter failed to return a swap transaction for sell")

            # Submit to Vanish
            record.status = "submitting_to_vanish"
            trade_resp = await self.vanish.create_trade(
                source_token_address=token,
                target_token_address=SOL_MINT,
                amount=token_balance,
                swap_transaction_b64=swap_tx,
                one_time_wallet=one_time_wallet,
            )
            tx_id = trade_resp.get("tx_id", "")
            jito_bundle_id = trade_resp.get("jito_bundle_id")
            record.vanish_tx_id = tx_id
            record.jito_bundle_id = jito_bundle_id
            record.solscan_url = f"https://solscan.io/tx/{tx_id}"
            logger.info(
                f"Sell submitted: tx_id={tx_id[:12]}... "
                f"jito_bundle={jito_bundle_id or 'n/a'}"
            )

            # Commit and wait for settlement
            record.status = "waiting_for_settlement"
            commit_result = await self.vanish.commit(tx_id)

            final_status = commit_result.get("status", "unknown")
            record.status = final_status
            record.vanish_fee = commit_result.get("vanish_fee")
            record.balance_changes = commit_result.get("balance_changes", [])
            record.settled_at = time.time()

            logger.info(
                f"Sell complete: {token[:12]}... status={final_status} "
                f"tx_id={tx_id[:12]}... solscan={record.solscan_url}"
            )

            await self._refresh_balances()

        except Exception as e:
            record.status = "error"
            record.error = str(e)
            record.settled_at = time.time()
            logger.error(f"Sell execution error for {token[:12]}...: {e}", exc_info=True)

        finally:
            self._tokens_in_flight.discard(token)
            self._active_trades -= 1

    async def _refresh_balances(self) -> None:
        try:
            self.balances = await self.vanish.get_balances()
            logger.debug(f"Balances refreshed: {len(self.balances)} token(s)")
        except Exception as e:
            logger.warning(f"Balance refresh failed: {e}")

    def get_scores_dict(self) -> Dict[str, Any]:
        return {addr: score.to_dict() for addr, score in self.scores.items()}

    def get_trades_list(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.trade_history[:50]]

    def get_balances_list(self) -> List[Dict[str, Any]]:
        return self.balances

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "active_trades": self._active_trades,
            "tokens_in_flight": list(self._tokens_in_flight),
            "watchlist": config.watchlist(),
            "thresholds": {
                "min_score": config.min_score(),
                "min_confidence": config.min_confidence(),
            },
            "user_address": self.vanish.user_address,
        }
