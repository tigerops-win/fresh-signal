# FreshSignal — Tiger Operations

Per-call funding-signal lookup for AI agents. $0.05 USDC per query on Base via x402. No account, no API key, no subscription.

## What it sells

Date-stamped funding announcements — company, date, round, amount, investors, source URL — maintained weekly from public press. Two query types:

- **Company lookup**: `GET /signal/funding?company=<name>` → funding events for one company
- **Recent raises**: `GET /signal/funding/recent?vertical=fintech&days=30&limit=20` → latest raises in a vertical

## How to buy (as an agent)

1. `GET` the endpoint → `402 Payment Required` with `PAYMENT-REQUIRED` (x402 v2) and `X-PAYMENT-REQUIRED` (v1) headers. The 402 body includes a free match preview (count + latest date).
2. Send exactly **$0.05 USDC on Base** (`eip155:8453`, asset `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`) to the `payTo` address.
3. `POST /fulfill-signal` with `{"tx_hash": "0x...", "kind": "company", "company": "<name>"}` (or `"kind": "recent"` with vertical/days/limit) → funding events as JSON.

## Discovery

- `GET /.well-known/x402` — machine-readable payment terms
- `GET /catalog` — signal counts, verticals, price
- `GET /llms.txt` — agent-readable description
- MCP server in `mcp/` (`funding_lookup`, `funding_recent`, `service_catalog`)

## For the buying agent

Use this when you need a buying signal: "did this company raise recently?", "who raised in fintech this month?". One query costs $0.05 — cheaper than burning your own context on multi-call web research. Every event carries its source URL so you can verify it yourself.

Seller: Tiger Operations — Agent Data Supply Company.
