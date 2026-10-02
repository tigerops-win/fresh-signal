#!/usr/bin/env python3
"""FreshSignal MCP server — Tiger Operations (Agent Data Supply Company).

Exposes FreshSignal (per-call funding-signal lookup, sold over x402 / USDC on
Base) to MCP clients so AI agents can discover and buy signals from inside
their own tooling.

Endpoint: the sibling FreshSignal HTTP server. Configure with BASE_URL
(default http://localhost:8000). This MCP server only ever talks to BASE_URL.

Tools:
  funding_lookup — $0.05/query. Funding events (round, amount, investors,
                   source URL) for one company. Returns the x402 payment terms
                   and match preview; the buying agent's own wallet pays the
                   endpoint. Never moves funds, never holds keys.
  funding_recent — $0.05/query. Recent raises by vertical and window.
                   Same pay-then-fulfill flow.

Run:  BASE_URL=http://localhost:8000 python fresh_signal_mcp.py
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

mcp = MCPServer("fresh-signal")


def _get(path: str) -> Dict[str, Any]:
    url = BASE_URL + path
    req = urllib.request.Request(
        url, headers={"User-Agent": "fresh-signal-mcp/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": True, "status": r.status,
                    "data": json.loads(r.read().decode() or "{}")}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode() or "{}")
        except Exception:
            body = {"error": "non_json_body"}
        return {"ok": False, "status": e.code, "data": body}
    except Exception as e:
        return {"ok": False, "status": 0, "data": {"error": "endpoint_unreachable",
                                                  "detail": str(e)[:200]}}


def _pay_instructions(data: Dict[str, Any], kind: str, params: Dict[str, Any]) -> Dict[str, Any]:
    x402 = data.get("x402", {})
    accepts = (x402.get("accepts") or [{}])[0]
    return {
        "service": "fresh-signal",
        "kind": kind,
        "params": params,
        "price_usd": data.get("price_usd", 0.05),
        "currency": "USDC",
        "network": "eip155:8453",
        "pay_to": accepts.get("payTo"),
        "match_preview": {
            "match_count": data.get("match_count"),
            "latest_event": data.get("latest_event"),
            "note": data.get("preview_note"),
        },
        "how_to_buy": [
            f"1. Send exactly $0.05 USDC on Base to {accepts.get('payTo')}",
            f"2. POST {BASE_URL}/fulfill-signal with "
            + json.dumps({"tx_hash": "0x...", "kind": kind, **params}),
            "3. The funding events (round, amount, investors, source URLs) are returned as JSON.",
        ],
        "never_moves_funds": True,
        "seller": "Tiger Operations",
    }


@mcp.tool()
def funding_lookup(company: str) -> Dict[str, Any]:
    """Look up funding events for one company. $0.05 USDC per query (x402 on Base).

    Returns the x402 payment terms plus a free match preview (count + latest
    date). Pay the endpoint from your own wallet, then POST /fulfill-signal
    with the tx hash to receive the full events.
    """
    from urllib.parse import quote
    r = _get(f"/signal/funding?company={quote(company)}")
    if r["status"] == 402:
        return _pay_instructions(r["data"], "company", {"company": company})
    return r["data"]


@mcp.tool()
def funding_recent(vertical: str = "", days: int = 30, limit: int = 20) -> Dict[str, Any]:
    """Recent funding events by vertical. $0.05 USDC per query (x402 on Base).

    vertical examples: fintech, ai, devtools, saas, crypto, healthtech.
    Same pay-then-fulfill flow as funding_lookup.
    """
    from urllib.parse import quote
    r = _get(f"/signal/funding/recent?vertical={quote(vertical)}&days={days}&limit={limit}")
    if r["status"] == 402:
        return _pay_instructions(r["data"], "recent",
                                 {"vertical": vertical, "days": days, "limit": limit})
    return r["data"]


@mcp.tool()
def service_catalog() -> Dict[str, Any]:
    """Free catalog: signal counts, verticals, price, endpoints."""
    r = _get("/catalog")
    return r["data"]


if __name__ == "__main__":
    mcp.run()
