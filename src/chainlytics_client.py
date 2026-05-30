"""
hackathon/src/chainlytics_client.py

Chainlytics API client.

Calls POST /v1/score to retrieve the TOON (Token-Oriented Object Notation) signal:
    decision_score   float 0-10   Weighted composite score (>= 7.0 = strong buy)
    action           str          BUY_SCALED | BUY | WAIT | AVOID | SELL
    confidence       float 0-1    Factor agreement ratio
    insider_risk     str          LOW | MEDIUM | HIGH
    regime           str          STABLE | TRANSITION | CHAOTIC
    ttl_s            int          Recommended client-side cache TTL in seconds
    _meta            dict         Per-factor scores and gate diagnostics

All config values come from config.py. No hardcoded URLs or keys.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from . import config

logger = logging.getLogger("chainlytics_client")


@dataclass
class TOONScore:
    token_address: str
    chain: str
    decision_score: float
    action: str
    confidence: float
    insider_risk: str
    regime: str
    ttl_s: int
    meta: Dict[str, Any] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    @property
    def is_buy_signal(self) -> bool:
        return self.action in ("BUY", "BUY_SCALED") and self.error is None

    @property
    def is_strong_buy(self) -> bool:
        return self.action == "BUY_SCALED" and self.error is None

    @property
    def cache_expired(self) -> bool:
        return (time.time() - self.fetched_at) >= self.ttl_s

    def passes_threshold(self) -> bool:
        """
        Returns True when the score and confidence clear the configured thresholds.
        Action-agnostic -- used for both BUY and SELL routing in the executor.
        """
        return (
            self.error is None
            and self.decision_score >= config.min_score()
            and self.confidence >= config.min_confidence()
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_address": self.token_address,
            "chain": self.chain,
            "decision_score": self.decision_score,
            "action": self.action,
            "confidence": self.confidence,
            "insider_risk": self.insider_risk,
            "regime": self.regime,
            "ttl_s": self.ttl_s,
            "fetched_at": self.fetched_at,
            "error": self.error,
        }


class ChainalyticsClient:
    def __init__(self):
        self._base_url = config.chainlytics_api_url().rstrip("/")
        self._api_key = config.chainlytics_api_key()
        self._chain = config.chainlytics_chain()
        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
        }
        logger.info(f"ChainalyticsClient ready: api_url={self._base_url}")

    async def score(self, token_address: str) -> TOONScore:
        """
        Call POST /v1/score and return a structured TOONScore.
        token_address and chain are sent as query parameters (not JSON body).
        On network or API error, returns a TOONScore with error set and action=AVOID.
        """
        url = f"{self._base_url}/v1/score"
        params = {"token_address": token_address, "chain": self._chain}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=self._headers, params=params)
                resp.raise_for_status()
                envelope = resp.json()

            if not envelope.get("success"):
                err = envelope.get("error", "unknown error from Chainlytics")
                logger.warning(f"Chainlytics score error for {token_address[:12]}...: {err}")
                return _error_score(token_address, self._chain, err)

            data = envelope.get("data", {})
            score = TOONScore(
                token_address=token_address,
                chain=self._chain,
                decision_score=float(data.get("decision_score", 0.0)),
                action=data.get("action", "AVOID"),
                confidence=float(data.get("confidence", 0.0)),
                insider_risk=data.get("insider_risk", "HIGH"),
                regime=data.get("regime", "CHAOTIC"),
                ttl_s=int(data.get("ttl_s", 60)),
                meta=data.get("_meta", {}),
            )
            logger.info(
                f"Score: {token_address[:12]}... "
                f"score={score.decision_score:.2f} action={score.action} "
                f"conf={score.confidence:.2f} regime={score.regime}"
            )
            return score

        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(f"Chainlytics HTTP error for {token_address[:12]}...: {err}")
            return _error_score(token_address, self._chain, err)

        except Exception as e:
            logger.error(f"Chainlytics exception for {token_address[:12]}...: {e}", exc_info=True)
            return _error_score(token_address, self._chain, str(e))


def _error_score(token_address: str, chain: str, error: str) -> TOONScore:
    return TOONScore(
        token_address=token_address,
        chain=chain,
        decision_score=0.0,
        action="AVOID",
        confidence=0.0,
        insider_risk="HIGH",
        regime="CHAOTIC",
        ttl_s=30,
        error=error,
    )
