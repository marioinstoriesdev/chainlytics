"""
hackathon/src/vanish_client.py

Vanish Core API client.

Handles all three Ed25519 signing formats (read, trade, withdraw) and every
endpoint documented at https://core.vanish.trade/guide/integration:

    GET  /deposit_address
    POST /account/balances
    POST /account/pending
    GET  /trade/one-time-wallet
    POST /trade/create
    POST /commit  (with polling until terminal status)
    POST /withdraw/create

All config values come from config.py. No hardcoded constants.

Ed25519 signing uses PyNaCl. The Solana keypair is read as 64 bytes:
    bytes[0:32]  = private key seed (passed to nacl.signing.SigningKey)
    bytes[32:64] = public key (verified against derived key)

Signature encoding: base64 (not base58 or hex), per Vanish spec.
Timestamps: Unix milliseconds as string.
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

_TERMINAL_STATUSES = {"completed", "failed", "expired", "rejected"}


class VanishClient:
    def __init__(self):
        keypair_bytes = config.solana_keypair_bytes()
        seed = keypair_bytes[:32]
        self._signing_key = nacl.signing.SigningKey(seed)
        self._verify_key = self._signing_key.verify_key
        self._user_address = base58.b58encode(bytes(self._verify_key)).decode()

        self._base_url = config.vanish_api_url().rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "x-api-key": config.vanish_api_key(),
        }
        logger.info(
            f"VanishClient ready: user_address={self._user_address[:12]}... "
            f"api_url={self._base_url}"
        )

    @property
    def user_address(self) -> str:
        return self._user_address

    # -- Signing helpers

    def _sign_b64(self, message: str) -> str:
        sig = self._signing_key.sign(message.encode("utf-8")).signature
        return base64.b64encode(sig).decode("utf-8")

    def _read_signature(self, timestamp: str) -> str:
        msg = (
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n"
            "\n"
            f"Details: read:{timestamp}"
        )
        return self._sign_b64(msg)

    def _trade_signature(
        self,
        source_token: str,
        target_token: str,
        amount: str,
        loan_additional_sol: str,
        timestamp: str,
        jito_tip_amount: str,
    ) -> str:
        msg = (
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n"
            "\n"
            f"Details: trade:{source_token}:{target_token}:{amount}:{loan_additional_sol}:{timestamp}:{jito_tip_amount}"
        )
        return self._sign_b64(msg)

    def _withdraw_signature(
        self,
        token_address: str,
        amount: str,
        additional_sol: str,
        timestamp: str,
    ) -> str:
        msg = (
            "By signing, I hereby agree to Vanish's Terms of Service and agree to be bound by them "
            "(docs.vanish.trade/legal/TOS)\n"
            "\n"
            f"Details: withdraw:{token_address}:{amount}:{additional_sol}:{timestamp}"
        )
        return self._sign_b64(msg)

    # -- HTTP helpers

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: Dict) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=self._headers, json=body)
            resp.raise_for_status()
            return resp.json()

    # -- Account endpoints

    async def get_deposit_address(self, token_address: str = SOL_NATIVE_MINT) -> str:
        """Return the deposit address for a given token (SOL by default)."""
        data = await self._get("/deposit_address", params={"token_address": token_address})
        return data["address"]

    async def get_balances(self) -> List[Dict[str, Any]]:
        """Return list of {token_address, balance, program_id} for the user."""
        ts = str(int(time.time() * 1000))
        sig = self._read_signature(ts)
        return await self._post(
            "/account/balances",
            {
                "user_address": self._user_address,
                "timestamp": ts,
                "signature": sig,
            },
        )

    async def get_pending(self) -> List[Dict[str, Any]]:
        """Return any uncommitted transactions for startup recovery."""
        ts = str(int(time.time() * 1000))
        sig = self._read_signature(ts)
        return await self._post(
            "/account/pending",
            {
                "user_address": self._user_address,
                "timestamp": ts,
                "signature": sig,
            },
        )

    # -- Trade endpoints

    async def get_one_time_wallet(self) -> str:
        """Return a fresh one-time wallet address. Use once per trade only."""
        data = await self._get("/trade/one-time-wallet")
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
        Submit a private swap trade to Vanish.

        swap_transaction_b64 must be:
            - a base64-encoded unsigned Solana swap transaction
            - built with one_time_wallet as the transaction signer (userPublicKey)
            - sourced from any DEX aggregator (Jupiter recommended)

        Returns {"tx_id": str, "jito_bundle_id": str|None, "transaction": str|None}
        """
        ts = str(int(time.time() * 1000))
        loan = str(config.loan_additional_sol())
        tip = str(config.jito_tip_amount())
        amt = str(amount)

        sig = self._trade_signature(
            source_token=source_token_address,
            target_token=target_token_address,
            amount=amt,
            loan_additional_sol=loan,
            timestamp=ts,
            jito_tip_amount=tip,
        )

        body = {
            "user_address": self._user_address,
            "source_token_address": source_token_address,
            "target_token_address": target_token_address,
            "amount": amt,
            "swap_transaction": swap_transaction_b64,
            "one_time_wallet": one_time_wallet,
            "loan_additional_sol": loan,
            "jito_tip_amount": tip,
            "split_repay": config.split_repay(),
            "timestamp": ts,
            "user_signature": sig,
        }
        return await self._post("/trade/create", body)

    async def commit(self, tx_id: str) -> Dict[str, Any]:
        """
        Commit a transaction and return its final status.
        Polls /commit until a terminal status is reached or commit_max_polls exhausted.

        Terminal statuses: completed, failed, expired, rejected
        """
        poll_interval = config.commit_poll_interval_seconds()
        max_polls = config.commit_max_polls()

        for poll in range(max_polls):
            result = await self._post("/commit", {"tx_id": tx_id})
            status = result.get("status", "pending")
            logger.debug(f"commit poll {poll + 1}/{max_polls}: tx_id={tx_id[:12]}... status={status}")

            if status in _TERMINAL_STATUSES:
                if status == "completed":
                    changes = result.get("balance_changes", [])
                    logger.info(
                        f"Trade settled: tx_id={tx_id[:12]}... "
                        f"vanish_fee={result.get('vanish_fee')} "
                        f"balance_changes={changes}"
                    )
                elif status == "rejected":
                    logger.warning(
                        f"Trade rejected by compliance screening: tx_id={tx_id[:12]}... "
                        f"Funds will be refunded to originating wallet."
                    )
                else:
                    logger.warning(f"Trade ended with status={status}: tx_id={tx_id[:12]}...")
                return result

            await asyncio.sleep(poll_interval)

        logger.error(f"commit timed out after {max_polls} polls: tx_id={tx_id[:12]}...")
        return {"status": "timeout", "tx_id": tx_id}

    async def recover_pending(self) -> None:
        """
        On startup: fetch any uncommitted transactions from prior sessions and commit them.
        Call once before starting the execution loop.
        """
        try:
            pending = await self.get_pending()
            if not pending:
                logger.info("No pending Vanish transactions to recover.")
                return
            logger.info(f"Recovering {len(pending)} pending Vanish transaction(s)...")
            for action in pending:
                tx_id = action.get("tx_id", "")
                result = await self.commit(tx_id)
                if not result.get("already_processed"):
                    logger.info(
                        f"Recovered: action_type={action.get('action_type')} "
                        f"status={result.get('status')}"
                    )
        except Exception as e:
            logger.error(f"Pending recovery error: {e}", exc_info=True)

    async def withdraw(
        self,
        token_address: str,
        amount: int,
        additional_sol: int = 0,
    ) -> Dict[str, Any]:
        """
        Create a withdrawal. The returned transaction_data must be broadcast via your RPC.
        After broadcast, call commit() with the on-chain tx signature.
        """
        ts = str(int(time.time() * 1000))
        amt = str(amount)
        add_sol = str(additional_sol)
        sig = self._withdraw_signature(token_address, amt, add_sol, ts)

        result = await self._post(
            "/withdraw/create",
            {
                "user_address": self._user_address,
                "token_address": token_address,
                "amount": amt,
                "additional_sol": add_sol,
                "timestamp": ts,
                "user_signature": sig,
            },
        )
        logger.info(f"Withdraw created: tx_id={result.get('tx_id', '')[:12]}...")
        return result
