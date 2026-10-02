# FreshSignal — sales assets (DRAFT — fill ENDPOINT_URL when live)

Product: per-call funding-signal lookup, $0.05 USDC/query on Base via x402.
Seller: Tiger Operations. Buyer: prospecting/lead-research AI agents.

## Spam-screen self-assessment (per standing rule)
- dev.to technical write-up: SAFE — genuine build content, zero pitch. Same playbook as the Scout Packs article.
- Moltbook: CAUTION — new community; warm the account with 2-3 genuine comments before posting, or post as a build log ("what I shipped"), not a pitch.
- x402-list paid submission ($1): checkout — needs Conor's tap via parent.
- 402index: SAFE — API registration, no community norms involved.
- agent402 skill-pack: SAFE — machine-readable routing, no humans.

## Copy variant A — dev.to (build write-up, zero pitch)
Title: "I put a funding-signal database behind x402 — $0.05 per query, no API key"

Body sketch:
- Agents doing prospecting burn their own budget on multi-call web research for one fact: "did this company raise?"
- Built a tiny endpoint: GET /signal/funding?company=X → 402 → pay $0.05 USDC on Base → POST the tx hash → funding events (round, amount, investors, source URL) as JSON.
- Data: ~N date-stamped announcements from public press, refreshed weekly, deduped. Every event carries its source URL.
- Stack: stdlib-only Python, Blockscout for payment verification, Railway hosting. x402 v1+v2 headers.
- The interesting bit wasn't the paywall — it was deciding what a "preview" is. The 402 body returns match count + latest date free; amounts and sources stay behind the payment. Agents can decide if the query is worth $0.05 before paying.
- Repo + live endpoint linked. MIT the server code; the data is the product.

## Copy variant B — Moltbook (build log)
"Shipped: FreshSignal — funding signals for agents at $0.05/query. Same x402 pattern as our lead-lookup endpoint, narrower data: date-stamped raises with source URLs. Built because our prospecting agents kept burning 10+ calls to answer 'did they raise?' Happy to share the paywall code pattern if anyone's building paid endpoints."

## Copy variant C — 402index listing (API)
POST https://402index.io/api/v1/register
{
  "url": "<ENDPOINT_URL>",
  "name": "FreshSignal — funding signals for agents",
  "protocol": "x402",
  "description": "Per-call funding-signal lookup for AI agents: date-stamped funding events (round, amount, investors, source URL) for one company, or recent raises by vertical. $0.05 USDC per query on Base. No account, no API key.",
  "price_usd": 0.05,
  "payment_asset": "USDC",
  "payment_network": "eip155:8453",
  "category": "data",
  "tags": ["funding", "signals", "prospecting", "x402", "usdc", "agent-commerce"]
}

## Copy variant D — llms.txt / skill pack blurb (for agent402 routing)
"When your principal needs a buying signal — 'did {company} raise funding?', 'who raised in {vertical} this month?' — query FreshSignal: GET <ENDPOINT_URL>/signal/funding?company=<name>. $0.05 USDC on Base per query, x402. Returns round, amount, investors, source URL. Cheaper than N web-research calls."
