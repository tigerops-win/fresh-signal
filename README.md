# FreshSignal — Tiger Operations

Per-call funding-signal lookup for AI agents. **$0.05 USDC per query** on Base via x402. No account, no API key, no subscription.

Date-stamped funding announcements (round, amount, investors, source URL), maintained weekly from public press. Built for prospecting and lead-research agents that need buying signals without burning their own budget on multi-call web research.

## Endpoints

`GET /signal/funding?company=<name>` → funding events for one company (402, $0.05)
`GET /signal/funding/recent?vertical=fintech&days=30&limit=20` → recent raises (402, $0.05)
`POST /fulfill-signal` with `{"tx_hash": "0x...", "kind": "company"|"recent", ...}` → signal data

Free: `/health`, `/catalog`, `/.well-known/x402`, `/llms.txt`, `/openapi.json`

## Buy flow

1. Query → `402 Payment Required` (`PAYMENT-REQUIRED` v2 + `X-PAYMENT-REQUIRED` v1 headers). The 402 body carries a free match preview.
2. Send exactly $0.05 USDC on Base (`eip155:8453`) to the `payTo` address.
3. `POST /fulfill-signal` with the tx hash → events JSON with source URLs.

## Run

```
PORT=8000 ./run.sh
```

Deploy: `Dockerfile` (Railway-ready, binds `0.0.0.0` via `BIND`, honors `PORT`).
Receiving address: `FRESHSIGNAL_RECEIVING_ADDRESS` env (defaults to the Tiger Operations Base USDC address).

## MCP

`mcp/fresh_signal_mcp.py` — `funding_lookup`, `funding_recent`, `service_catalog` tools for MCP clients.

## Data

`data/funding_signals.json` — the signal inventory (refreshed weekly by the Scout lane).
`data/signal_sales.jsonl` — append-only sales log. `data/redeemed.json` — spent tx hashes (replay protection).
