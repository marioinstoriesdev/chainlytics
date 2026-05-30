# Chainlytics x Vanish: Signal-to-Silent-Execution

**Private Solana trading powered by the Chainlytics Intelligence Score.**

Chainlytics detects the buy signal. Vanish executes the trade privately.
Your wallet never signs anything on-chain.

---

## What This Is

A production-ready execution SDK that combines two live APIs:

**Chainlytics** (`api.chainlytics.dev`) — a token intelligence API that collapses 340+ raw
on-chain fields into six decision-grade signals via a single REST call. One request. Under one
second. No schema normalization. No multi-provider orchestration.

**Vanish Core** (`core-api.vanish.trade`) — private swap execution via disposable one-time
wallets routed through Jito bundles. The originating wallet never appears as a transaction signer
on-chain. From submission to settlement: ~200ms.

**Combined:** when Chainlytics fires a BUY signal above your threshold, the system automatically
executes the trade through Vanish. Your wallet is invisible. The trade is private. The signal is real.

---

## What You Need

**1. A Chainlytics API key** — get one at [chainlytics.dev](https://chainlytics.dev)

| Plan | Price | What you get |
|------|-------|-------------|
| STARTER | $19/mo | Raw data endpoints + private trading via Vanish. Assemble your own signal from token security, holder stats, volume, social analysis, and wallet intelligence data. |
| PRO | $49/mo | Everything in STARTER, plus the Chainlytics Intelligence Score — a single decision-grade TOON signal (BUY / BUY_SCALED / WAIT / SELL / AVOID) that pre-computes all factors for you. |
| ENTERPRISE | Custom | Dedicated infrastructure, custom rate limits, SLA. |

**2. Your Solana wallet keypair** — a 64-byte JSON array. This is your Vanish trading wallet:
funds deposit here and withdraw here (Vanish same-wallet-in, same-wallet-out compliance).

```bash
solana-keygen new --outfile wallet.json
cat wallet.json   # paste this array into config.yaml -> solana.keypair
```

**You do NOT need a Vanish API key.** Chainlytics holds the Vanish operator key server-side.
Your Chainlytics subscription covers private trading access.

---

## How It Works

```
Your config.yaml
  chainlytics.api_key  ──> Chainlytics API (PRO/ENTERPRISE)
  solana.keypair       ──> local Ed25519 signing (compliance)

Execution loop:
  1. POST /v1/score               ──> TOON signal (score, action, confidence)
  2. GET  /v1/vanish/one-time-wallet   ──> fresh disposable wallet address
  3. Jupiter v6 quote + swap      ──> unsigned swap transaction (OTW as signer)
  4. POST /v1/vanish/trade        ──> Chainlytics proxies to Vanish + adds operator key
  5. POST /v1/vanish/commit       ──> poll until settlement (~200ms)
```

Your keypair signs the trade message locally (for Vanish compliance). Chainlytics proxies the
signed request to Vanish using its operator key. You never interact with Vanish directly.

---

## Quick Start

```bash
git clone https://github.com/marioinstoriesdev/chainlytics
cd chainlytics
pip install -r requirements.txt

cp config.example.yaml config.yaml
# Edit config.yaml: set chainlytics.api_key and solana.keypair

python -m src.server    # dashboard at http://localhost:3000
```

---

## Project Layout

```
chainlytics/
  config.example.yaml       Configuration template (copy to config.yaml)
  requirements.txt          Python dependencies
  src/
    config.py               Config loader (reads config.yaml, no hardcoded values)
    chainlytics_client.py   POST /v1/score -> TOONScore dataclass
    vanish_client.py        Vanish proxy client (routes through Chainlytics API)
    jupiter_client.py       Jupiter v6 unsigned swap transaction builder
    executor.py             Signal-to-execution loop (BUY + SELL paths)
    server.py               FastAPI dashboard + trade history API
```

---

## Chainlytics API Endpoints

All endpoints are available at `https://api.chainlytics.dev`. Authentication via `X-API-Key` header.

### Scoring (PRO / ENTERPRISE)

**POST /v1/score** — Chainlytics Intelligence Score (TOON)

```bash
curl -X POST "https://api.chainlytics.dev/v1/score?token_address=MINT&chain=sol" \
  -H "X-API-Key: ce_pro_your_key"
```

Response:
```json
{
  "success": true,
  "data": {
    "decision_score": 8.2,
    "action": "BUY_SCALED",
    "confidence": 0.91,
    "insider_risk": "LOW",
    "regime": "STABLE",
    "ttl_s": 30
  }
}
```

Actions: `BUY_SCALED` (>=8.5) · `BUY` (>=7.0) · `WAIT` (>=5.0) · `SELL` · `AVOID`

### Data Endpoints (STARTER and above)

| Endpoint | Description |
|----------|-------------|
| GET /v1/token/security | Contract safety: mint authority, freeze, taxes, honeypot |
| GET /v1/token/info | Price, market cap, liquidity, volume, holder count |
| GET /v1/token/holders | Top holder distribution and concentration |
| GET /v1/token/traders | Top trader stats and smart money activity |
| GET /v1/market/trending | Trending tokens by volume and momentum |
| GET /v1/wallet/holdings | Token holdings for a wallet address |
| GET /v1/wallet/stats | Win rate, ROI, PnL for a wallet |
| GET /v1/portfolio/pnl | Portfolio PnL and trade history |
| GET /v1/social | Social trust signals and community metrics |

STARTER plan gives you all the raw signals — combine them to build your own scoring logic.
PRO gives you the pre-computed TOON score that does it for you.

### Private Trading Endpoints (STARTER and above)

All `/v1/vanish/*` endpoints proxy to Vanish Core using Chainlytics' operator key.
Your wallet keypair is used only for local signing — never sent over the wire.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /v1/vanish/one-time-wallet | Fresh one-time wallet per trade |
| GET | /v1/vanish/deposit-address | Deposit address for a token |
| POST | /v1/vanish/trade | Submit a private swap |
| POST | /v1/vanish/commit | Commit / poll transaction status |
| POST | /v1/vanish/balance | Vanish balance for your wallet |
| POST | /v1/vanish/pending | Uncommitted transactions (startup recovery) |
| POST | /v1/vanish/withdraw | Withdraw back to originating wallet |

---

## The STARTER Path: Assemble Your Own Signal

No PRO key? STARTER gives you all the raw data. Here is one approach:

```python
from src.chainlytics_client import ChainalyticsClient

# Fetch raw token data
token_info    = await client.get("/v1/token/info",    {"token_address": mint})
token_holders = await client.get("/v1/token/holders", {"token_address": mint})
social        = await client.get("/v1/social",        {"token_address": mint})

# Build your own score
buy_signal = (
    token_info["liquidity_usd"] > 50_000
    and token_holders["top10_pct"] < 0.30
    and social["sentiment_score"] > 0.6
    and token_info["volume_1h_usd"] > 10_000
)
```

Then use the same `/v1/vanish/*` endpoints for private execution.
The technological moat is the PRO score — but you can get close by combining the raw signals.

---

## Signing (handled automatically by vanish_client.py)

Vanish requires Ed25519 signatures for trade, withdraw, and read operations.
`VanishClient` generates all three formats locally using your keypair:

```
read    format: "...TOS\n\nDetails: read:{timestamp}"
trade   format: "...TOS\n\nDetails: trade:{src}:{tgt}:{amount}:{loan}:{ts}:{tip}"
withdraw format: "...TOS\n\nDetails: withdraw:{token}:{amount}:{sol}:{ts}"
```

Timestamps are Unix milliseconds. Signatures are base64-encoded.

---

## Configuration Reference

See `config.example.yaml` for all keys with comments. The required minimum:

```yaml
chainlytics:
  api_key: "ce_pro_your_key_here"   # from chainlytics.dev

solana:
  keypair: [12, 34, ...]            # 64-byte wallet array

execution:
  watchlist:
    - "TokenMintAddress..."
  min_score: 7.0                    # PRO only; set 0.0 for STARTER
  trade_amount_lamports: 5000000    # 0.005 SOL per trade
```

---

## Links

- Chainlytics: [chainlytics.dev](https://chainlytics.dev)
- Vanish Core docs: [core.vanish.trade/start/introduction](https://core.vanish.trade/start/introduction)
- Questions: contact@chainlytics.dev
