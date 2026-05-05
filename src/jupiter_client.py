"""
hackathon/src/jupiter_client.py

Jupiter DEX aggregator client.

Builds unsigned Solana swap transactions for the Vanish execution flow.
The critical requirement: one_time_wallet must be passed as userPublicKey so
that Jupiter builds the transaction with the Vanish disposable address as the
signer, not the user's real wallet.

Endpoints used:
    GET  https://quote-api.jup.ag/v6/quote   -- get best route for a swap
    POST https://quote-api.jup.ag/v6/swap    -- serialize the unsigned swap tx

The returned swapTransaction is base64-encoded and unsigned by the user.
It is passed directly to Vanish POST /trade/create as swap_transaction.
Vanish signs it using the one-time wallet's private key and submits via Jito.

No credentials required. Jupiter is a public API.
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("jupiter_client")

_JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
_JUPITER_SWAP_URL = "https://quote-api.jup.ag/v6/swap"

# Native SOL mint address on Solana mainnet
SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterClient:
    def __init__(self):
        logger.info("JupiterClient ready: quote-api.jup.ag/v6")

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount_lamports: int,
        slippage_bps: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Get the best swap quote from Jupiter.

        Args:
            input_mint:       Input token mint (SOL_MINT for native SOL)
            output_mint:      Output token mint (the token to buy)
            amount_lamports:  Input amount in lamports (or base units for SPL)
            slippage_bps:     Max slippage in basis points (default 1% = 100 bps)

        Returns:
            Quote dict from Jupiter, or None on error.
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_lamports),
            "slippageBps": str(slippage_bps),
            "swapMode": "ExactIn",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_JUPITER_QUOTE_URL, params=params)
                resp.raise_for_status()
                quote = resp.json()

            out_amount = quote.get("outAmount", "0")
            price_impact = quote.get("priceImpactPct", "0")
            logger.info(
                f"Jupiter quote: {input_mint[:12]}... -> {output_mint[:12]}... "
                f"in={amount_lamports} out={out_amount} priceImpact={price_impact}%"
            )
            return quote

        except httpx.HTTPStatusError as e:
            logger.error(f"Jupiter quote HTTP error: {e.response.status_code} {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Jupiter quote exception: {e}", exc_info=True)
            return None

    async def build_swap_transaction(
        self,
        quote: Dict[str, Any],
        one_time_wallet: str,
    ) -> Optional[str]:
        """
        Build an unsigned swap transaction from a Jupiter quote.

        The one_time_wallet address is used as userPublicKey -- Jupiter builds
        the transaction with this wallet as the expected signer. The transaction
        is returned unsigned. Vanish will sign it using the one-time wallet's
        private key.

        Args:
            quote:            Quote dict from get_quote()
            one_time_wallet:  Disposable address from Vanish GET /trade/one-time-wallet

        Returns:
            Base64-encoded unsigned swap transaction string, or None on error.
        """
        body = {
            "quoteResponse": quote,
            "userPublicKey": one_time_wallet,
            "wrapAndUnwrapSol": True,
            "skipUserAccountsRpcCalls": False,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    _JUPITER_SWAP_URL,
                    headers={"Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()

            swap_tx = data.get("swapTransaction")
            if not swap_tx:
                logger.error(f"Jupiter swap response missing swapTransaction: {data}")
                return None

            logger.info(
                f"Jupiter swap tx built: signer={one_time_wallet[:12]}... "
                f"tx_len={len(swap_tx)} chars (base64)"
            )
            return swap_tx

        except httpx.HTTPStatusError as e:
            logger.error(f"Jupiter swap HTTP error: {e.response.status_code} {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Jupiter swap exception: {e}", exc_info=True)
            return None

    async def build_private_swap(
        self,
        output_mint: str,
        amount_lamports: int,
        one_time_wallet: str,
        input_mint: str = SOL_MINT,
        slippage_bps: int = 100,
    ) -> Optional[str]:
        """
        Convenience method: get quote + build swap transaction in one call.

        Returns base64 unsigned swap transaction ready for Vanish /trade/create,
        or None if either step fails.
        """
        quote = await self.get_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_lamports=amount_lamports,
            slippage_bps=slippage_bps,
        )
        if quote is None:
            return None
        return await self.build_swap_transaction(quote, one_time_wallet)
