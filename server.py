#!/usr/bin/env python3
"""FreshSignal — Tiger Operations (Agent Data Supply Company).

Per-call funding-signal lookup for AI agents. Python stdlib only.

- GET /signal/funding?company=<name>   -> funding events for that company (402, $0.05 USDC)
- GET /signal/funding/recent?vertical=<v>&days=30&limit=20 -> recent funding events (402, $0.05)
- POST /fulfill-signal {tx_hash, kind, ...} -> on-chain payment verification
  (Base USDC transfer to the configured receiving address, via Blockscout's
  free API), then the signal data.

Paid in USDC on Base (eip155:8453). No agent in this stack holds private keys.

Data: data/funding_signals.json — maintained, deduped, source-URL'd funding
announcements (public press). Refreshed weekly by the Scout lane.

Run:  FRESHSIGNAL_RECEIVING_ADDRESS=0x... ./run.sh   (PORT, BIND envs supported)
"""

import base64
import html as html_lib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote_plus

# ---------------------------------------------------------------- config
PORT = int(os.environ.get("PORT", "8000"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Public receiving address (Conor's Base USDC address — public, not a secret).
# Env override wins; sales pause only if the result isn't a valid address.
DEFAULT_RECEIVING = "0xAF7B70D8487EE6193701597E67f56A5902d23913"
RECEIVING = os.environ.get("FRESHSIGNAL_RECEIVING_ADDRESS", DEFAULT_RECEIVING).strip().lower()
ZERO = "0x0000000000000000000000000000000000000000"
SALES_ENABLED = bool(RECEIVING) and RECEIVING != ZERO and bool(re.fullmatch(r"0x[0-9a-f]{40}", RECEIVING or ""))
PUBLIC_BASE = os.environ.get("FRESHSIGNAL_PUBLIC_BASE", "")

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Base native USDC, 6 decimals
NETWORK = "eip155:8453"
BLOCKSCOUT = "https://base.blockscout.com/api/v2"
REDEEMED_PATH = os.path.join(BASE_DIR, "data", "redeemed.json")
SALES_LOG = os.path.join(BASE_DIR, "data", "signal_sales.jsonl")
SIGNALS_PATH = os.path.join(BASE_DIR, "data", "funding_signals.json")

PRICE_USD = 0.05
AMOUNT = 50_000  # $0.05 in 6-decimal USDC
SERVICE_DESC = ("Funding-signal lookup — date-stamped funding events (round, amount, "
                "investors, source URL) for one company query, or recent raises by "
                "vertical. Maintained weekly. Tiger Operations.")

TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

# ---------------------------------------------------------------- data
def load_signals():
    try:
        with open(SIGNALS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

SIGNALS = load_signals()

def find_company(query):
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for s in SIGNALS:
        name = str(s.get("company", "")).lower()
        if q in name or name in q:
            out.append(s)
    out.sort(key=lambda s: s.get("date", ""), reverse=True)
    return out

def recent_signals(vertical=None, days=30, limit=20):
    cutoff = time.time() - days * 86400
    v = (vertical or "").strip().lower()
    out = []
    for s in SIGNALS:
        try:
            ts = datetime.strptime(s.get("date", "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        if v and str(s.get("vertical", "")).lower() != v:
            continue
        out.append(s)
    out.sort(key=lambda s: s.get("date", ""), reverse=True)
    return out[:max(1, min(limit, 50))]

def verticals():
    return sorted({str(s.get("vertical", "")).lower() for s in SIGNALS if s.get("vertical")})

# --------------------------------------------------------------- helpers
def load_redeemed():
    try:
        with open(REDEEMED_PATH) as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_redeemed(hashes):
    tmp = REDEEMED_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(sorted(hashes), f)
    os.replace(tmp, REDEEMED_PATH)

def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "fresh-signal/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def verify_signal_payment(tx_hash):
    """Returns (ok, detail)."""
    if not SALES_ENABLED:
        return False, "sales_paused: receiving address not configured"
    if not TX_RE.match(tx_hash or ""):
        return False, "bad_tx_hash"
    tx_hash = tx_hash.lower()
    redeemed = load_redeemed()
    if tx_hash in redeemed:
        return False, "already_redeemed"
    try:
        tx = fetch_json(f"{BLOCKSCOUT}/transactions/{tx_hash}")
    except urllib.error.HTTPError as e:
        return (False, "tx_not_found") if e.code == 404 else (False, f"chain_lookup_failed:{e.code}")
    except Exception:
        return False, "chain_lookup_failed"
    if str(tx.get("status", "")).lower() != "ok":
        return False, "tx_not_successful"
    try:
        ts_raw = (tx.get("timestamp") or "").replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_raw).timestamp()
        if time.time() - ts > 30 * 86400:
            return False, "tx_too_old"
    except Exception:
        pass
    for t in tx.get("token_transfers", []) or []:
        try:
            tok_obj = t.get("token") or {}
            tok = (tok_obj.get("address_hash") or tok_obj.get("address") or "").lower()
            to = (t.get("to") or {}).get("hash", "").lower()
            val = int((t.get("total") or {}).get("value", 0))
            sender = (t.get("from") or {}).get("hash", "").lower()
        except (ValueError, TypeError):
            continue
        if tok == USDC_BASE.lower() and to == RECEIVING and val >= AMOUNT:
            redeemed.add(tx_hash)
            save_redeemed(redeemed)
            return True, {"sender": sender, "value": val}
    return False, "no_matching_usdc_transfer"

def log_sale(kind, params, tx_hash, sender):
    try:
        os.makedirs(os.path.dirname(SALES_LOG), exist_ok=True)
        with open(SALES_LOG, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "kind": kind, "params": params, "tx_hash": tx_hash.lower(),
                "sender": sender, "amount_usd": PRICE_USD,
            }) + "\n")
    except Exception:
        pass

def base_url(handler):
    if PUBLIC_BASE:
        return PUBLIC_BASE.rstrip("/")
    host = handler.headers.get("Host", f"127.0.0.1:{PORT}")
    return f"http://{host}"

def payment_accept(handler, resource, description):
    return {
        "scheme": "exact",
        "network": NETWORK,
        "maxAmountRequired": str(AMOUNT),
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": RECEIVING if SALES_ENABLED else ZERO,
        "maxTimeoutSeconds": 300,
        "asset": USDC_BASE,
        "extra": {"name": "USDC", "version": "2"},
    }

def x402_terms(handler, resource, description):
    accept = payment_accept(handler, resource, description)
    return {
        "x402Version": 2,
        "accepts": [accept],
        "sales_enabled": SALES_ENABLED,
        **({} if SALES_ENABLED else {"error": "Sales paused: seller receiving address not configured yet."}),
    }

def paywall_headers(handler, body):
    terms_b64_v2 = base64.b64encode(json.dumps(body["x402"]).encode()).decode()
    terms_v1 = {"x402Version": 1, "accepts": [{
        "scheme": "exact", "network": NETWORK, "maxAmountRequired": str(AMOUNT),
        "resource": body["x402"]["accepts"][0]["resource"],
        "description": body["x402"]["accepts"][0]["description"],
        "mimeType": "application/json", "payTo": body["x402"]["accepts"][0]["payTo"],
        "maxTimeoutSeconds": 300, "asset": USDC_BASE, "extra": {"name": "USDC", "version": "2"}}]}
    terms_b64_v1 = base64.b64encode(json.dumps(terms_v1).encode()).decode()
    return {"PAYMENT-REQUIRED": terms_b64_v2, "X-PAYMENT-REQUIRED": terms_b64_v1}

def how_to_pay(kind, params_desc):
    return [
        f"1. Send exactly $0.05 in USDC on Base to {RECEIVING if SALES_ENABLED else '(address pending)'}",
        f"2. POST /fulfill-signal with {{\"tx_hash\": \"0x...\", \"kind\": \"{kind}\", {params_desc}}}",
        "3. Receive the funding-signal data as JSON.",
    ]

# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "fresh-signal/1.0"
    _hits = {}

    def limited(self, cap=120, window=60):
        ip = self.client_address[0]
        now = time.time()
        h = [t for t in self._hits.get(ip, []) if now - t < window]
        h.append(now)
        self._hits[ip] = h
        return len(h) > cap

    def send_json(self, code, obj, extra_headers=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code, text, ctype="text/plain; charset=utf-8"):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def params(self):
        qs = urlparse(self.path).query
        out = {}
        for p in qs.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                out[k] = unquote_plus(v)
        return out

    def do_GET(self):
        if self.limited():
            return self.send_json(429, {"error": "rate_limited", "retry_after_seconds": 60})
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/":
                return self.landing()
            if path == "/health":
                return self.send_json(200, {"ok": True, "sales_enabled": SALES_ENABLED,
                                            "signals": len(SIGNALS), "verticals": verticals()})
            if path == "/catalog":
                return self.send_json(200, self.catalog())
            if path == "/.well-known/x402":
                return self.send_json(200, self.well_known())
            if path == "/llms.txt":
                return self.send_text(200, LLMS_TXT)
            if path == "/openapi.json":
                return self.send_json(200, OPENAPI_DOC)
            if path == "/signal/funding":
                return self.company_signal()
            if path == "/signal/funding/recent":
                return self.recent_signal()
            return self.send_json(404, {"error": "not_found"})
        except Exception:
            return self.send_json(500, {"error": "internal"})

    def do_POST(self):
        if self.limited(cap=30):
            return self.send_json(429, {"error": "rate_limited", "retry_after_seconds": 60})
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/fulfill-signal":
                return self.fulfill_signal()
            return self.send_json(404, {"error": "not_found"})
        except Exception:
            return self.send_json(500, {"error": "internal"})

    # -- routes
    def landing(self):
        n = len(SIGNALS)
        verts = ", ".join(verticals()[:8])
        pill = ('<span class="pill"><span class="dot"></span>Live — accepting USDC on Base</span>'
                if SALES_ENABLED else '<span class="pill off"><span class="dot"></span>Paused</span>')
        html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FreshSignal — Funding signals for agents · Tiger Operations</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;background:#faf8f4;color:#1d2126;line-height:1.6}}
.wrap{{max-width:860px;margin:0 auto;padding:0 28px 80px}}
.top{{display:flex;justify-content:space-between;align-items:center;padding:22px 0;border-bottom:1px solid #e4ded2}}
.brand{{font-size:12px;font-weight:800;letter-spacing:.2em;color:#5d6672}}
.pill{{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;font-weight:650;color:#b45309;background:rgba(180,83,9,.07);border:1px solid #d9a441;padding:7px 14px;border-radius:999px}}
.pill.off{{color:#5d6672;background:transparent;border-color:#d3cbb9}}
.dot{{width:8px;height:8px;border-radius:50%;background:#b45309}}
h1{{font-size:clamp(34px,5vw,52px);letter-spacing:-.025em;margin:56px 0 16px}}
.lede{{font-size:18px;color:#5d6672;max-width:600px}}
.card{{background:#fff;border:1px solid #e4ded2;border-radius:12px;padding:24px;margin:28px 0}}
.card h3{{margin:0 0 8px;font-size:16px}}
code{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;background:#f4f1ea;border:1px solid #e4ded2;padding:2px 8px;border-radius:5px}}
table{{width:100%;border-collapse:collapse;font-size:14px;background:#fff;border:1px solid #e4ded2;border-radius:12px;overflow:hidden}}
td{{padding:12px 18px;border-bottom:1px solid #e4ded2;vertical-align:top}}
tr:last-child td{{border-bottom:0}}
td.c{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:#b45309;white-space:nowrap}}
td.d{{color:#5d6672}}
.foot{{border-top:1px solid #e4ded2;padding-top:24px;font-size:13px;color:#9098a3;display:flex;justify-content:space-between}}
</style></head><body><div class="wrap">
<header class="top"><span class="brand">TIGER OPERATIONS</span>{pill}</header>
<h1>Funding signals, per call.</h1>
<p class="lede">Date-stamped funding announcements — round, amount, investors, source URL — for AI agents doing prospecting and lead research. <strong>{n} events</strong> tracked ({html_lib.escape(verts)}). $0.05 USDC per query on Base. No account, no key, no subscription.</p>
<div class="card"><h3>Company lookup</h3><p><code>GET /signal/funding?company=acme</code> → 402 paywall → pay $0.05 → <code>POST /fulfill-signal</code> with your tx hash → funding events as JSON.</p></div>
<div class="card"><h3>Recent raises</h3><p><code>GET /signal/funding/recent?vertical=fintech&amp;days=30&amp;limit=20</code> → the latest raises in a vertical. Same $0.05 flow.</p></div>
<h2 style="font-size:22px;margin:40px 0 16px">Endpoints</h2>
<table>
<tr><td class="c">GET /signal/funding?company=</td><td class="d">Funding events for one company — 402 ($0.05)</td></tr>
<tr><td class="c">GET /signal/funding/recent</td><td class="d">Recent raises by vertical — 402 ($0.05)</td></tr>
<tr><td class="c">POST /fulfill-signal</td><td class="d">Submit {{"tx_hash","kind",...}} — paid</td></tr>
<tr><td class="c">GET /catalog</td><td class="d">Service catalog — free</td></tr>
<tr><td class="c">GET /.well-known/x402</td><td class="d">Machine-readable payment terms — free</td></tr>
<tr><td class="c">GET /llms.txt</td><td class="d">Agent-readable description — free</td></tr>
</table>
<footer class="foot"><span>Tiger Operations — Agent Data Supply Company</span><span>Paid in USDC on Base</span></footer>
</div></body></html>"""
        self.send_text(200, html, "text/html; charset=utf-8")

    def catalog(self):
        return {"seller": "Tiger Operations", "service": "fresh-signal",
                "signals_tracked": len(SIGNALS), "verticals": verticals(),
                "price_usd": PRICE_USD, "currency": "USDC", "network": NETWORK,
                "endpoints": {
                    "/signal/funding": "funding events for one company (?company=)",
                    "/signal/funding/recent": "recent raises (?vertical=&days=30&limit=20)",
                },
                "sales_enabled": SALES_ENABLED}

    def well_known(self):
        base = base_url(self)
        resources = []
        for resource, desc in [
            (f"{base}/signal/funding",
             SERVICE_DESC + " Query: /signal/funding?company=<name>."),
            (f"{base}/signal/funding/recent",
             SERVICE_DESC + " Query: /signal/funding/recent?vertical=<v>&days=30&limit=20."),
        ]:
            resources.append({"resource": resource,
                              "accepts": [payment_accept(self, resource, desc)]})
        return {"x402Version": 2, "sales_enabled": SALES_ENABLED, "resources": resources}

    def company_signal(self):
        p = self.params()
        query = (p.get("company", "") or "").strip()
        if not query:
            return self.send_json(400, {"error": "missing_company",
                "usage": "GET /signal/funding?company=<company name>",
                "price_usd": PRICE_USD, "currency": "USDC", "network": NETWORK})
        matches = find_company(query)
        if not matches:
            return self.send_json(404, {"error": "no_match", "company": query,
                "hint": "No funding events tracked for this company yet."})
        base = base_url(self)
        resource = f"{base}/signal/funding?company={query}"
        desc = SERVICE_DESC + f" Company query: {query}."
        terms = x402_terms(self, resource, desc)
        body = {"error": "payment_required", "service": "funding-signal", "kind": "company",
                "company": query, "match_count": len(matches),
                "latest_event": matches[0].get("date"),
                "preview_note": "Match count and latest date are free. Full events (round, amount, investors, source URLs) unlock after payment.",
                "price_usd": PRICE_USD, "currency": "USDC", "network": NETWORK,
                "sales_enabled": SALES_ENABLED, "x402": terms,
                "how_to_pay": how_to_pay("company", '"company": "..."')}
        self.send_json(402, body, paywall_headers(self, body))

    def recent_signal(self):
        p = self.params()
        vertical = (p.get("vertical", "") or "").strip().lower() or None
        try:
            days = max(1, min(int(p.get("days", "30")), 365))
        except ValueError:
            days = 30
        try:
            limit = max(1, min(int(p.get("limit", "20")), 50))
        except ValueError:
            limit = 20
        matches = recent_signals(vertical, days, limit)
        if not matches:
            return self.send_json(404, {"error": "no_match", "vertical": vertical,
                "days": days, "hint": "No tracked raises in this window."})
        base = base_url(self)
        resource = f"{base}/signal/funding/recent?vertical={vertical or ''}&days={days}&limit={limit}"
        desc = SERVICE_DESC + f" Recent raises: vertical={vertical or 'all'}, days={days}, limit={limit}."
        terms = x402_terms(self, resource, desc)
        body = {"error": "payment_required", "service": "funding-signal", "kind": "recent",
                "vertical": vertical, "days": days, "limit": limit,
                "match_count": len(matches),
                "preview_note": "Match count is free. Full events (company, round, amount, investors, source URLs) unlock after payment.",
                "price_usd": PRICE_USD, "currency": "USDC", "network": NETWORK,
                "sales_enabled": SALES_ENABLED, "x402": terms,
                "how_to_pay": how_to_pay("recent", '"vertical": "...", "days": 30, "limit": 20')}
        self.send_json(402, body, paywall_headers(self, body))

    def fulfill_signal(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self.send_json(400, {"error": "bad_json"})
        kind = str(payload.get("kind", "")).strip()
        tx_hash = str(payload.get("tx_hash", ""))
        if kind == "company":
            query = str(payload.get("company", "")).strip()
            if not query:
                return self.send_json(400, {"error": "missing_company"})
            events = find_company(query)
            params = {"company": query}
        elif kind == "recent":
            vertical = str(payload.get("vertical", "") or "").strip().lower() or None
            try:
                days = max(1, min(int(payload.get("days", 30)), 365))
            except (ValueError, TypeError):
                days = 30
            try:
                limit = max(1, min(int(payload.get("limit", 20)), 50))
            except (ValueError, TypeError):
                limit = 20
            events = recent_signals(vertical, days, limit)
            params = {"vertical": vertical, "days": days, "limit": limit}
        else:
            return self.send_json(400, {"error": "unknown_kind",
                "kinds": ["company", "recent"]})
        if not events:
            return self.send_json(404, {"error": "no_match"})
        ok, detail = verify_signal_payment(tx_hash)
        if not ok:
            return self.send_json(402, {"error": "payment_not_verified", "detail": detail,
                "pay": how_to_pay(kind, json.dumps(params)[1:-1])})
        sender = detail.get("sender", "unknown") if isinstance(detail, dict) else "unknown"
        log_sale(kind, params, tx_hash, sender)
        return self.send_json(200, {
            "receipt": "ok", "service": "funding-signal", "kind": kind,
            "params": params, "tx_hash": tx_hash.lower(), "price_usd": PRICE_USD,
            "events": events,
            "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": "Funding events with source URLs for provenance. Data refreshed weekly.",
        })

    def log_message(self, *a):
        pass  # quiet

LLMS_TXT = """# FreshSignal — Tiger Operations
Funding-signal lookup for AI agents, over x402 (USDC on Base, eip155:8453). $0.05 per query.

## Endpoints
- GET /signal/funding?company=<name> -> 402 with PAYMENT-REQUIRED (x402 v2) and X-PAYMENT-REQUIRED (v1) headers. Match count + latest date are free in the 402 body.
- GET /signal/funding/recent?vertical=<v>&days=30&limit=20 -> same 402 flow for recent raises by vertical.
- POST /fulfill-signal {"tx_hash":"0x...","kind":"company","company":"<name>"} -> funding events JSON (round, amount, investors, source_url).
- POST /fulfill-signal {"tx_hash":"0x...","kind":"recent","vertical":"fintech","days":30,"limit":20} -> recent events JSON.

## Flow
1. Query an endpoint -> 402 with exact terms ($0.05 USDC on Base).
2. Send exactly $0.05 USDC on Base to the payTo address.
3. POST /fulfill-signal with the tx hash -> events delivered.

## Discovery
- /.well-known/x402 — machine-readable payment terms.
- /catalog — service catalog, verticals, signal counts.
"""

OPENAPI_DOC = {
    "openapi": "3.0.3",
    "info": {"title": "FreshSignal", "version": "1.0.0",
             "description": "Funding-signal lookup for AI agents. $0.05 USDC per query on Base via x402. Tiger Operations."},
    "paths": {
        "/signal/funding": {"get": {"summary": "Funding events for a company",
            "parameters": [{"name": "company", "in": "query", "required": True, "schema": {"type": "string"}}],
            "responses": {"402": {"description": "Payment required ($0.05 USDC on Base)"}}}},
        "/signal/funding/recent": {"get": {"summary": "Recent funding events by vertical",
            "parameters": [
                {"name": "vertical", "in": "query", "schema": {"type": "string"}},
                {"name": "days", "in": "query", "schema": {"type": "integer", "default": 30}},
                {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}}],
            "responses": {"402": {"description": "Payment required ($0.05 USDC on Base)"}}}},
        "/fulfill-signal": {"post": {"summary": "Submit payment, receive signal data",
            "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
            "responses": {"200": {"description": "Signal data delivered"}}}},
    },
}

if __name__ == "__main__":
    bind_host = os.environ.get("BIND", "0.0.0.0")
    print(f"fresh-signal on {bind_host}:{PORT}  sales_enabled={SALES_ENABLED}  signals={len(SIGNALS)}", flush=True)
    ThreadingHTTPServer((bind_host, PORT), Handler).serve_forever()
