"""
hackathon/src/vanish_client.py
Vanish Core client -- routes through Chainlytics API.

Chainlytics holds the Vanish operator key server-side. Users never need
their own Vanish API key. This client authenticates to Chainlytics using
the subscriber's Chainlytics API key, while signing trade messages locally
with the user's own Solana keypair (required for Vanish compliance).

Signing is performed locally using PyNaCl (Ed25519). The Chainlytics proxy
forwards the user's signature and wallet address to Vanish, which verifies
ownership. This enforces Vanish's same-wallet-in, same-wallet-out policy
per subscriber wallet.

Endpoints used (via Chainlytics proxy):
  GET  /v1/vanish/one-time-wallet
  GET  /v1/vanish/deposit-address
  POST /v1/vanish/trade
  POST /v1/vanish/commit       (polled until terminal status)
  POST /v1/vanish/balance
  POST /v1/vanish/pending
  POST /v1/vanish/withdraw

All config values come from config.py. Nothing is hardcoded.
Ed25519 signing uses PyNaCl. Keypair is 64 bytes: seed[0:32] + pubkey[32:64].
Signatures are base64-encoded. Timestamps are Unix milliseconds as strings.
"""

import asyncio
import base64
import logging
import time
from typing import Any, Dict, List, Optional

import base58
import httpx
import nacl.signing

from . import config

logger = logging.getLogger("vanish_client")

SOL_NATIVE_MINT = "11111111111111111111111111111111"
_TERMINAL = {"completed", "failed", "expired", "rejected"}


class VanishClient:
    """
    Vanish Core client that routes all requests through the Chainlytics API.
    The subscriber's Chainlytics key is the only credential needed.
    The user's Solana keypair is used for local message signing only.
    """

    def __init__(self):
        keypair = config.solana_keypair_bytes()
        seed = keypair[:32]
        self._signing_key = nacl.signing.SigningKey(seed)
        self._verify_key  = self._signing_key.verify_key
        self._user_address = base58.b58encode(bytes(self._verify_key)).decode()

        # All Vanish calls route through Chainlytics /v1/vanish/
        self._base_url = config.chainlytics_api_url().rstrip("/") + "/v1/vanish"
        self._headers  = {
            "Content-Type": "application/json",
            "X-API-Key":    config.chainlytics_api_key(),
        }
        logger.info(
            "VanishClient ready: wallet=%s... endpoint=%s",
            self._user_address[:12],
            self._base_url,
        )

    @property
    def user_address(self) -> str:
        return self._user_address

    # -- Signing helpers ----------------------------------------------------

    def _sign_b64(self, message: str) -> str:
        sig = self._signing_key.sign(message.encode()).signature
        return base64.b64encode(sig).decode()

    def _read_sig(self, ts: str) -> str:
        return self._sign_b64(
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n\nDetails: read:" + ts
        )

    def _trade_sig(self, src: str, tgt: str, amt: str, loan: str, ts: str, tip: str) -> str:
        return self._sign_b64(
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n\n"
            f"Details: trade:{src}:{tgt}:{amt}:{loan}:{ts}:{tip}"
        )

    def _withdraw_sig(self, token: str, amt: str, add_sol: str, ts: str) -> str:
        return self._sign_b64(
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n\n"
            f"Details: withdraw:{token}:{amt}:{add_sol}:{ts}"
        )

    # -- HTTP helpers -------------------------------------------------------

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(url, headers=self._headers, params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, body: Dict) -> Any:
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(url, headers=self._headers, json=body)
            r.raise_for_status()
            return r.json()

    def _unwrap(self, resp: Any) -> Any:
        """Chainlytics wraps Vanish responses in {success, data}."""
        if isinstance(resp, dict) and "data" in resp:
            return resp["data"]
        return resp

    # -- Account endpoints --------------------------------------------------

    async def get_deposit_address(self, token_address: str = SOL_NATIVE_MINT) -> str:
        """Deposit address for the given token. Always fetch fresh before depositing."""
        data = self._unwrap(await self._get("/deposit-address", {"token_address": token_address}))
        return data["address"]

    async def get_balances(self) -> List[Dict[str, Any]]:
        """All token balances in the user's Vanish account."""
        ts = str(int(time.time() * 1000))
        return self._unwrap(await self._post("/balance", {
            "user_address": self._user_address,
            "timestamp":    ts,
            "signature":    self._read_sig(ts),
        }))

    async def get_pending(self) -> List[Dict[str, Any]]:
        """Uncommitted transactions. Call on startup to recover interrupted flows."""
        ts = str(int(time.time() * 1000))
        return self._unwrap(await self._post("/pending", {
            "user_address": self._user_address,
            "timestamp":    ts,
            "signature":    self._read_sig(ts),
        }))

    # -- Trade endpoints ----------------------------------------------------

    async def get_one_time_wallet(self) -> str:
        """Fresh one-time wallet address. Fetch a new one for every trade."""
        data = self._unwrap(await self._get("/one-time-wallet"))
        return data["address"]

    async def create_trade(
        self,
        source_token_address: str,
        target_token_address: str,
        amount: int,
        swap_transaction_b64: str,
        one_time_wallet: str,
    ) -> Dict[str, Any]:
        """
        Submit a private swap through Chainlytics to Vanish.

        swap_transaction_b64 must be a base64-encoded UNSIGNED Solana swap
        transaction built via Jupiter v6, with one_time_wallet as the signer
        (userPublicKey). Do NOT pre-sign the transaction.

        Returns {"tx_id": str, "jito_bundle_id": str|None, "transaction": str|None}
        """
        ts   = str(int(time.time() * 1000))
        loan = str(config.loan_additional_sol())
        tip  = str(config.jito_tip_amount())
        amt  = str(amount)
        sig  = self._trade_sig(source_token_address, target_token_address, amt, loan, ts, tip)

        return self._unwrap(await self._post("/trade", {
            "user_address":         self._user_address,
            "source_token_address": source_token_address,
            "target_token_address": target_token_address,
            "amount":               amt,
            "swap_transaction":     swap_transaction_b64,
            "one_time_wallet":      one_time_wallet,
            "loan_additional_sol":  loan,
            "jito_tip_amount":      tip,
            "split_repay":          config.split_repay(),
            "timestamp":            ts,
            "user_signature":       sig,
        }))

    async def commit(self, tx_id: str) -> Dict[str, Any]:
        """
        Commit a transaction and poll until a terminal status is reached.
        Terminal: completed, failed, expired, rejected.
        Must be called for every outcome -- including failures -- to unfreeze balance.
        """
        interval  = config.commit_poll_interval_seconds()
        max_polls = config.commit_max_polls()
        for poll in range(max_polls):
            result = self._unwrap(await self._post("/commit", {"tx_id": tx_id}))
            status = result.get("status", "pending")
            logger.debug("commit poll %d/%d tx=%s... status=%s", poll + 1, max_polls, tx_id[:12], status)
            if status in _TERMINAL:
                if status == "completed":
                    logger.info(
                        "Trade settled: tx=%s... fee=%s changes=%s",
                        tx_id[:12], result.get("vanish_fee"), result.get("balance_changes"),
                    )
                elif status == "rejected":
                    logger.warning("Trade rejected by compliance: tx=%s... Funds refunded.", tx_id[:12])
                else:
                    logger.warning("Trade ended status=%s tx=%s...", status, tx_id[:12])
                return result
            await asyncio.sleep(interval)
        logger.error("commit timed out after %d polls: tx=%s...", max_polls, tx_id[:12])
        return {"status": "timeout", "tx_id": tx_id}

    async def recover_pending(self) -> None:
        """On startup: fetch and commit any transactions from prior sessions."""
        try:
            pending = await self.get_pending()
            if not pending:
                logger.info("No pending Vanish transactions to recover.")
                return
            logger.info("Recovering %d pending transaction(s)...", len(pending))
            for action in pending:
                tx_id  = action.get("tx_id", "")
                result = await self.commit(tx_id)
                if not result.get("already_processed"):
                    logger.info("Recovered: type=%s status=%s", action.get("action_type"), result.get("status"))
        except Exception as e:
            logger.error("Pending recovery error: %s", e, exc_info=True)

    async def withdraw(self, token_address: str, amount: int, additional_sol: int = 0) -> Dict[str, Any]:
        """
        Create a withdrawal. Broadcast returned transaction_data via your RPC,
        then call commit() with the on-chain signature.
        """
        ts      = str(int(time.time() * 1000))
        amt     = str(amount)
        add_sol = str(additional_sol)
        result  = self._unwrap(await self._post("/withdraw", {
            "user_address":   self._user_address,
            "token_address":  token_address,
            "amount":         amt,
            "additional_sol": add_sol,
            "timestamp":      ts,
            "user_signature": self._withdraw_sig(token_address, amt, add_sol, ts),
        }))
        logger.info("Withdraw created: tx=%s...", result.get("tx_id", "")[:12])
        return result
