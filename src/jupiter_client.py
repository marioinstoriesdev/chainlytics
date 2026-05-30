"""
Jupiter v6 Swap Client

Builds unsigned swap transactions via the Jupiter Aggregator API v6.
Used by executor.py to get swap routes for Vanish private trade execution.

SOL_MINT: wrapped SOL mint address on Solana mainnet.
"""

import base64
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"

JUPITER_QUOTE_URL = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_URL  = "https://quote-api.jup.ag/v6/swap"


class JupiterClient:
    """
    Async client for Jupiter Aggregator v6.

    Fetches swap quotes and builds unsigned swap transactions
    that can be signed by a Vanish one-time wallet.
    """

    def __init__(self, slippage_bps: int = 50):
        self.slippage_bps = slippage_bps

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: Optional[int] = None,
    ) -> Optional[dict]:
        """
        Fetch a swap quote from Jupiter.

        Args:
            input_mint:    Input token mint address.
            output_mint:   Output token mint address.
            amount:        Amount in smallest units (lamports for SOL).
            slippage_bps:  Slippage tolerance in basis points (default: self.slippage_bps).

        Returns:
            Quote dict from Jupiter or None on failure.
        """
        slippage = slippage_bps if slippage_bps is not None else self.slippage_bps
        params = {
            "inputMint":   input_mint,
            "outputMint":  output_mint,
            "amount":      str(amount),
            "slippageBps": str(slippage),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    JUPITER_QUOTE_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"Jupiter quote HTTP {resp.status}")
                    return None
        except Exception as e:
            logger.warning(f"Jupiter quote error: {e}")
            return None

    async def build_private_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        user_public_key: str,
        slippage_bps: Optional[int] = None,
    ) -> Optional[str]:
        """
        Build an unsigned swap transaction via Jupiter v6.

        Args:
            input_mint:      Input token mint (e.g. SOL_MINT for SOL).
            output_mint:     Output token mint (token to buy/sell).
            amount:          Amount in smallest units.
            user_public_key: Signer public key (Vanish one-time wallet address).
            slippage_bps:    Slippage in basis points.

        Returns:
            Base64-encoded unsigned transaction string, or None on failure.
        """
        quote = await self.get_quote(input_mint, output_mint, amount, slippage_bps)
        if not quote:
            logger.warning("Jupiter: no quote returned, cannot build swap")
            return None

        payload = {
            "quoteResponse":    quote,
            "userPublicKey":    user_public_key,
            "wrapAndUnwrapSol": True,
            "asLegacyTransaction": False,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    JUPITER_SWAP_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("swapTransaction")
                    body = await resp.text()
                    logger.warning(f"Jupiter swap HTTP {resp.status}: {body[:200]}")
                    return None
        except Exception as e:
            logger.warning(f"Jupiter swap error: {e}")
            return None
