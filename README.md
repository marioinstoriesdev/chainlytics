# Chainlytics x Vanish: Signal-to-Silent-Execution

Solana Frontier Hackathon 2026 -- Vanish Track ($10K)

Chainlytics detects the buy signal. Vanish executes the trade. Your wallet never signed a thing.

---

## What This Is

A production-ready pipeline that combines two live APIs:

1. Chainlytics POST /v1/score: a decision-grade token intelligence API that collapses
   340+ raw on-chain fields into six actionable, LLM-ready signals via a single REST
   call. One API call. Under 200ms. No schema normalization. No multi-provider
   orchestration. Real data, no mocks.

2. Vanish Core API: private swap execution via disposable one-time wallets routed through
   Jito bundles. The originating wallet never appears as a transaction signer on-chain.
   From submission to settlement: ~200ms.

Combined: when Chainlytics fires a BUY signal above your configured threshold, the
system automatically executes the trade through Vanish. Your wallet is invisible.
The trade is private. The signal is real.

---

## The Problem: The RPC Read Layer Nobody Talks About

When any app, bot, or AI agent wants to read the blockchain, it does not query the chain
directly. It sends a request to a Remote Procedure Call (RPC) node. That node is like a
hyperactive librarian living inside the network: you ask "What is the balance of this
wallet?" or "What were the last 100 transactions for this token?" and it replies.

The problem: the library grows by thousands of pages per second, millions of people are
asking questions simultaneously, and the librarian sometimes hands you a version of the
book that is 2, 5, 8, or even 15 seconds old -- confirmed by RPC provider reports in
2025-2026. In traditional markets, 15 seconds is annoying. In Solana, 15 seconds is
catastrophic. A token can move 30-50% in that window.

### The Four Deadly Symptoms

Staleness. Public RPC nodes show 2-15 second delays during peak load. Bots buy at prices
that no longer exist, causing massive slippage and lost edge. A token rises 25% in 12
seconds; your bot pays 20% more than it should.

Noise floor. Over 95% of tokens are spam or rugs. The read layer mixes them with
legitimate tokens, contaminating every signal. Tuning in is like receiving 50 radio
stations at once.

Orchestration tax. To get a complete picture of a single token, applications must make
5-8 separate API calls across multiple providers. Total latency: 1,300-2,000ms per
decision. In a market that moves every second, that is unacceptable.

Schema chaos. Every provider uses different field names and JSON structures. LLMs and
bots break silently when a field is renamed. There is no obvious error -- just wrong
decisions made confidently.

### Who Is Paying for This Today

High-frequency trading bots lose 5-30% of their competitive edge to stale or noisy data.

Autonomous AI agents are already a real market: more than 17,000 agents launched in DeFi
since 2025 (DWF Ventures data), already accounting for approximately 19% of on-chain
activity. They need clean, decision-ready data, not raw JSON dumps.

DeFi applications suffer user experience collapse and users lose money on outdated prices.

### Why Existing Solutions Keep Failing

Using multiple providers does not solve the problem. You now maintain three API
integrations, three keys, three schemas, and three failure points. When data conflicts,
you add arbitration logic. Total latency becomes the sum of every provider. A data problem
becomes an expensive, fragile engineering problem.

Building your own indexer takes 6-18 months of engineering, a team of 3-5 specialists,
and $5,000-$50,000 per month in infrastructure. Only viable for well-funded teams.

Traditional data APIs (The Graph, Helius, QuickNode) improve raw speed but still deliver
200-400 raw fields per response. None were designed for AI agents that need decisions, not
data dumps.

None of these approaches solve the real 2026 pain: autonomous agents need instant
decisions, not raw data.

---

## The Solution: One API Call. Six Fields. Immediate Signal.

Chainlytics is a decision-grade token intelligence API. It sits between the raw on-chain
data layer and your execution system, absorbing the entire orchestration, normalization,
and filtering problem so your code does not have to.

A single POST /v1/score call condenses the following multi-source data pipeline into one
structured response with no post-processing required on the client:

Real-time chain scanning: new token discovery across Pump.fun, letsbonk, fourmeme, and
clanker; multi-chain trending token rankings at minimum 1-minute granularity sorted by
volume, smart money count, and market cap; real-time OHLCV and K-line data at 1m, 5m,
15m, 1h, 4h, and 1d resolution.

Token analytics: fundamentals, social links, Bonding Curve status, and liquidity pool
details; security signals covering honeypot detection, open source status, renounced
authority, wash trading detection, and rug ratio score (0-1); deep holder profiling across
Smart Money, KOL, rat trader, bundler, sniper, whale, and fresh wallet categories.

Wallet intelligence: real-time holdings and realized/unrealized P&L for any wallet;
live buy and sell tracking for Smart Money and KOL wallets; win rate, trade style, and
behavioral classification across all monitored addresses.

Chainlytics' proprietary scoring algorithm reduces the entire multi-source input into
the TOON schema (Token-Oriented Object Notation) -- six fields replacing 340:

    POST /v1/score
    { "token_address": "...", "chain": "sol" }

    {
      "decision_score": 7.84,   // 0-10  -- above 7.0 = strong buy
      "action":  "BUY_SCALED",  // BUY_SCALED | BUY | WAIT | AVOID | SELL
      "confidence": 0.91,       // 0-1   -- factor agreement ratio
      "insider_risk": "LOW",    // LOW | MEDIUM | HIGH
      "regime": "STABLE",       // STABLE | TRANSITION | CHAOTIC
      "ttl_s": 180              // recommended client-side cache TTL
    }

A 5-gate safety pipeline runs before the score is returned. Tokens that fail any gate
never produce a BUY signal -- liquidity floors, honeypot detection, volume thresholds,
wash trading detection, and rug pull signals are all hard-filtered before the score
reaches your system.

### Why TOON Matters for AI Systems

Raw on-chain JSON responses contain 200-400 fields. LLMs and trading agents cannot
consume that reliably: field names change, null values appear without warning, and
prompts bloat with irrelevant data. TOON reduces prompt token usage by 98%+. The
machine-readable `action` field requires zero NLP overhead for execution. The `ttl_s`
field enables autonomous caching logic -- no polling needed. The `_meta` object provides
full per-factor transparency when you need to explain a decision.

Chainlytics is the first AI-native token intelligence layer: purpose-built for LLM
agents, trading bots, and automated execution systems from day one.

---

## The Chainlytics + Vanish Combination

Vanish without signal: you execute privately but you are guessing what to buy.

Signal without Vanish: you know what to buy but you broadcast your strategy on-chain the
moment you execute. MEV searchers sandwich your transaction. Copy-trading bots clone your
position immediately. Competing funds see your holdings and front-run the next entry.

Chainlytics + Vanish is a closed loop where a scored signal flows directly into private
execution without ever touching the mempool as a user-signed transaction. The intelligence
is real. The execution is invisible.

Our wallet intelligence research confirms the edge: wallets using privacy-routed execution
show 68% less copy-trade inflow in the first 60 seconds following a buy compared to
standard smart-money wallets executing on-chain directly. The signal is worth more when
it cannot be observed. Vanish is what makes that true.

---

## Is This Legal?

Yes, clearly.

The on-chain data layer that powers Chainlytics is sourced from open-source tooling
(MIT licensed). The MIT license grants unrestricted rights -- including the right to use
the software to collect data and commercialize the result. The underlying blockchain data
is public ledger: no one owns a wallet's transaction history.

Chainlytics' scoring algorithm, gating logic, and TOON output schema are proprietary IP
built on open-source foundations. The combination -- scoring engine, 5-gate safety
pipeline, and TOON schema -- belongs to Chainlytics.

Vanish screens every transaction via Elliptic and Range before signing. This is not a
mixer. It is a privacy-routing DEX with institutional-grade compliance infrastructure
audited by Halborn. Rejected transactions are refunded to the originating wallet
automatically. The system surfaces rejected status clearly in the dashboard and logs.

Chainlytics is a decision-support tool. `confidence`, `regime`, and gate-derived fields
are probabilistic signals, not financial advice. Infrastructure classification applies.

---

## Who This Is For

Developers: replace 5-8 API integrations with one authenticated endpoint. Circuit
breaker, retry logic, and per-token adaptive caching are built in. Production-quality
from day one. Free tier available -- no credit card required.

Algorithmic traders: use `decision_score`, `action`, and `insider_risk` for entry
decisions, exit timing, or automated alerting on watchlists. PRO tier delivers the full
intelligence signal at $99/mo -- below Birdeye's $250 Premium tier.

AI agents and LLM systems: TOON is purpose-built for machine consumption. Zero schema
normalization. Zero NLP overhead on the `action` field. Compatible with any agent
framework that can make an HTTP POST request.

Enterprises: dedicated infrastructure, negotiated rate limits, SLA guarantees, and
cross-chain portfolio aggregation available. Contact for pricing.

---

## API Tiers

    FREE        $0/mo     Token intelligence -- explore the platform
    STARTER     $49/mo    Wallet analytics, holder profiling, portfolio tracking
    PRO         $99/mo    Full TOON score, 5-gate pipeline, trading simulator
    ENTERPRISE  Custom    Dedicated infrastructure, negotiated limits, SLAs

PRO tier is required for /v1/score access and is the tier this hackathon integration
uses. Rate limits: FREE 1K req/day, STARTER 50K/day, PRO 200K/day, ENTERPRISE unlimited.

Sign up at https://chainlytics.dev.

---

## Directory Structure

    hackathon/
      config.example.yaml    Config template -- copy to config.yaml and fill in values
      requirements.txt       Python dependencies
      src/
        config.py            Config loader (reads config.yaml)
        vanish_client.py     Vanish Core API client with Ed25519 signing
        chainlytics_client.py  Chainlytics /v1/score client
        jupiter_client.py    Jupiter DEX aggregator (unsigned swap tx builder)
        executor.py          Signal-to-execution loop (background asyncio task)
        server.py            FastAPI backend serving dashboard API + frontend
      frontend/
        index.html           Single-file dashboard (served by the backend)

---

## Setup

### 1. Install dependencies

    pip install -r requirements.txt

### 2. Configure

    cp config.example.yaml config.yaml

Edit config.yaml and fill in:
- vanish.api_key: your Vanish Core API key (request via discord.gg/vanishtrade)
- chainlytics.api_key: your Chainlytics PRO key (get one at chainlytics.dev)
- chainlytics.api_url: https://api.chainlytics.dev
- solana.keypair: your Solana wallet keypair as a JSON array of 64 integers
- solana.rpc_url: your Solana RPC endpoint (Triton One recommended)
- execution.watchlist: list of Solana token mint addresses to monitor
- execution.trade_amount_lamports: SOL per trade in lamports (keep small for demo)

To generate a keypair: `solana-keygen new --outfile keypair.json && cat keypair.json`
The output is the 64-integer array to paste under `solana.keypair`.

### 3. Get a Chainlytics API key

Sign up at https://chainlytics.dev to get a PRO API key.
PRO tier is required for /v1/score access.
Set `chainlytics.api_url` to `https://api.chainlytics.dev` and paste your key under
`chainlytics.api_key`. The key is passed via `X-API-Key` header on every request.

### 4. Fund your Vanish account

Open the dashboard at http://localhost:3000 after starting the server.
The deposit address bar at the top shows your Vanish deposit address.
Send a small amount of SOL to that address (0.05-0.10 SOL is enough for demo).
The system recovers any uncommitted transactions automatically on startup.

### 5. Start the execution server

    python -m src.server

Open http://localhost:3000 in your browser.

---

## How a Trade Executes

BUY / BUY_SCALED path (SOL -> token):

1. Background executor polls Chainlytics /v1/score for each token in the watchlist.
2. When decision_score >= min_score AND confidence >= min_confidence AND
   action in (BUY, BUY_SCALED): execution is triggered.
3. GET /trade/one-time-wallet from Vanish -- a fresh disposable address.
4. GET Jupiter quote for the swap (SOL as input, watchlist token as output).
5. POST Jupiter /v6/swap with one_time_wallet as userPublicKey -- returns unsigned tx.
6. POST Vanish /trade/create with the unsigned transaction.
7. Vanish signs with the one-time wallet's private key and routes via Jito bundle.
8. POST Vanish /commit -- poll until status == "completed".
9. Trade appears in the dashboard with Solscan link proving the user wallet did not sign.

SELL / SELL_SCALED path (token -> SOL):

1. When action is SELL or SELL_SCALED and passes the threshold, a sell is triggered.
2. Vanish balance is checked for the token. If no balance, the sell is skipped.
3. GET /trade/one-time-wallet from Vanish.
4. GET Jupiter quote for the reverse swap (token as input, SOL as output).
5. POST Jupiter /v6/swap with one_time_wallet as userPublicKey.
6. POST Vanish /trade/create and commit as above.
7. Trade appears in the feed with the same Solscan privacy proof.

The executor respects `ttl_s` from the TOON response: if a cached score has not expired,
it is reused without an additional API call. Scores are only re-fetched when the token's
own intelligence layer signals the data is stale.

---

## The Privacy Proof

Every completed trade shows a Solscan transaction link. Click it. The transaction signer
is the Vanish one-time wallet -- a disposable address that exists for exactly one trade.
The user wallet (your keypair address) appears nowhere in the transaction.

This is the core demo moment. Show it.

---

## Configuration Reference

All values are in config.yaml. Nothing is hardcoded in source files.

    vanish.api_url                    Vanish Core API base URL
    vanish.api_key                    Vanish API key
    chainlytics.api_url               Chainlytics API base URL
    chainlytics.api_key               Chainlytics API key (PRO tier required for /v1/score)
    chainlytics.chain                 Chain identifier (sol)
    solana.rpc_url                    Solana RPC endpoint
    solana.keypair                    64-integer JSON array (standard Solana keypair format)
    execution.watchlist               List of token mint addresses to monitor
    execution.min_score               Minimum decision_score to trigger trade (0-10)
    execution.min_confidence          Minimum confidence to trigger trade (0-1)
    execution.trade_amount_lamports   SOL per trade in lamports
    execution.loan_additional_sol     Lamports loaned for ATA creation (refunded if unused)
    execution.jito_tip_amount         Jito tip in lamports (min 1,000,000)
    execution.split_repay             Vanish Trading Accounts to split output across (1-9)
    execution.poll_interval_seconds   Chainlytics polling frequency
    execution.commit_poll_interval_seconds  Vanish /commit poll frequency
    execution.commit_max_polls        Max /commit polls before timeout
    execution.max_concurrent_trades   Max simultaneous Vanish trades in flight
    server.host                       Dashboard server bind host
    server.port                       Dashboard server port

---

## Competitive Context

| Feature                          | Birdeye      | Helius        | Chainlytics         |
|----------------------------------|------------- |---------------|---------------------|
| Market data and OHLCV            | $39-$699/mo  | Partial       | Yes (FREE)          |
| Token security scan              | Partial      | No            | Yes (FREE)          |
| Holder analysis                  | Partial      | No            | Yes (STARTER+)      |
| Wallet intelligence and P&L      | Yes          | Partial       | Yes (STARTER+)      |
| Smart money signals              | Partial      | No            | Yes (PRO)           |
| Decision score 0-10              | No           | No            | Yes -- core product |
| 5-gate safety pipeline           | No           | No            | Yes -- exclusive    |
| AI-agent ready output (TOON)     | No           | No            | Yes -- exclusive    |
| Trading simulation               | No           | No            | Yes (PRO+)          |
| Multi-chain                      | Yes          | Solana only   | SOL + BSC (Base Q3) |
| Intelligence tier price          | $250/mo      | N/A           | $99/mo (PRO)        |

---

## Contact

Mario Casanova | mariosamuelcasanova@gmail.com | chainlytics.dev
