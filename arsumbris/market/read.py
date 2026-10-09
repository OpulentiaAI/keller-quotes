"""Operator-only, bounded market discovery. Never a supplier-cost oracle."""

import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

MAX_BYTES = 256 * 1024
MAX_INPUT = 4096
BLS_SERIES = "PCU331110331110"
SYMBOLS = {
    "MB-STE-0184": ("US Midwest hot-rolled coil FOB mill", "daily", 72),
    "MB-STE-0185": ("US cold-rolled coil FOB mill", "weekly", 240),
    "MB-STE-0883": ("US HDG hot-rolled base FOB mill", "weekly", 240),
}
DOMAINS = ("ryerson.com", "alro.com", "onlinemetals.com", "steelwarehouse.com")
SEARCH_FIELDS = {
    "family": {"carbon_steel": "carbon steel", "stainless_steel": "stainless steel"},
    "form": {"sheet": "sheet", "plate": "plate", "coil": "coil", "tube": "tube", "bar": "bar"},
    "topic": {"supplier": "supplier stock availability", "processing": "cutting processing capabilities", "specification": "material specifications tolerances"},
}


class InvalidRequest(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise InvalidRequest("Provider redirects are not permitted")


def validate(value):
    if not isinstance(value, dict) or set(value) - {"searches", "steel_symbols", "include_bls"}:
        raise InvalidRequest("Unknown market lookup fields")
    searches = value.get("searches", [])
    symbols = value.get("steel_symbols", [])
    bls = value.get("include_bls", False)
    if not isinstance(searches, list) or len(searches) > 3:
        raise InvalidRequest("At most three generic supplier searches")
    unique = []
    for item in searches:
        if not isinstance(item, dict) or set(item) != set(SEARCH_FIELDS):
            raise InvalidRequest("Search requires only public family, form and topic selectors")
        if any(not isinstance(item[k], str) or item[k] not in choices for k, choices in SEARCH_FIELDS.items()):
            raise InvalidRequest("Unsupported public search selector")
        query = "US Midwest " + " ".join(choices[item[k]] for k, choices in SEARCH_FIELDS.items())
        if query not in unique:
            unique.append(query)
    if not isinstance(symbols, list) or len(symbols) > 3 or any(not isinstance(s, str) or s not in SYMBOLS for s in symbols):
        raise InvalidRequest("Unknown or excessive steel symbols")
    if not isinstance(bls, bool) or not (unique or symbols or bls):
        raise InvalidRequest("Select at least one bounded lookup")
    return {"searches": unique, "steel_symbols": list(dict.fromkeys(symbols)), "include_bls": bls}


def fetch_json(url, headers=None, body=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})},
                                 data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None)
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(req, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InvalidRequest("Provider response exceeded byte budget")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise InvalidRequest("Invalid provider response")
    return data, hashlib.sha256(raw).hexdigest()


def positive(value):
    if isinstance(value, bool):
        raise InvalidRequest("Invalid numeric observation")
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise InvalidRequest("Invalid numeric observation")
    return n


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    u = urllib.parse.urlsplit(value)
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return None
    if not any(u.hostname == d or (u.hostname or "").endswith("." + d) for d in DOMAINS):
        return None
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))


def search(query, key, fetch):
    data, digest = fetch("https://api.exa.ai/search", {"x-api-key": key, "Content-Type": "application/json"},
                         {"query": query, "type": "auto", "numResults": 3, "includeDomains": list(DOMAINS)})
    if not isinstance(data.get("results"), list):
        raise InvalidRequest("Missing search results")
    results, seen = [], set()
    for row in data["results"][:3]:
        if not isinstance(row, dict):
            raise InvalidRequest("Invalid search result")
        url = safe_url(row.get("url"))
        if url and url not in seen:
            seen.add(url)
            results.append({"url": url, "title": str(row.get("title", ""))[:240],
                            "source_class": "discovery_only", "untrusted_text": True})
    return {"provider": "exa", "status": "ok", "query": query, "results": results,
            "response_sha256": digest, "next_cursor": None,
            "limitation": "Search locates supplier pages; it does not verify availability, scope, or a buy price."}


def bls_index(now, fetch):
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/" + BLS_SERIES + "?latest=true"
    data, digest = fetch(url)
    series = data.get("Results", {}).get("series", [])
    if data.get("status") != "REQUEST_SUCCEEDED" or len(series) != 1 or series[0].get("seriesID") != BLS_SERIES:
        raise InvalidRequest("Unavailable BLS series")
    observations = []
    for row in series[0].get("data", [])[:36]:
        period = row.get("period", "")
        if not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
            continue
        date = dt.date(int(row["year"]), int(period[1:]), 1)
        if date > now.date():
            raise InvalidRequest("Future BLS observation")
        observations.append((date, positive(row["value"])))
    if not observations:
        raise InvalidRequest("No monthly BLS observation")
    date, value = max(observations)
    return {"provider": "bls", "status": "ok", "source_class": "monthly_industry_index",
            "series": BLS_SERIES, "observation_period": date.strftime("%Y-%m"), "value": value,
            "unit": "index_points", "currency": None, "period_age_days": (now.date() - date).days,
            "stale": (now.date() - date).days > 90, "source_url": url, "response_sha256": digest,
            "limitation": "Monthly, potentially revised industry PPI; not USD per weight, real-time steel, or a supplier offer."}


def fastmarkets(symbols, token, now, fetch):
    url = "https://api.fastmarkets.com/physical/v2/Prices"
    data, digest = fetch(url, {"Authorization": "Bearer " + token,
                              "Content-Type": "application/x-www-form-urlencoded"},
                         urllib.parse.urlencode({"Symbols": ",".join(symbols)}).encode())
    instruments = data.get("instruments")
    if not isinstance(instruments, list) or len(instruments) != len(symbols):
        raise InvalidRequest("Incomplete Fastmarkets response")
    rows, seen = [], set()
    for instrument in instruments:
        symbol = instrument.get("symbol")
        if symbol not in symbols or symbol in seen:
            raise InvalidRequest("Unexpected Fastmarkets instrument")
        seen.add(symbol)
        prices = instrument.get("prices")
        if not isinstance(prices, list) or len(prices) != 1:
            raise InvalidRequest("Expected one latest assessment")
        price = prices[0]
        observed = dt.datetime.fromisoformat(price["assessmentDate"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise InvalidRequest("Assessment timezone missing")
        age = (now - observed).total_seconds()
        if age < -300:
            raise InvalidRequest("Future assessment")
        values = {key: positive(price[key]) for key in ("low", "mid", "high")}
        if not values["low"] <= values["mid"] <= values["high"]:
            raise InvalidRequest("Unordered assessment")
        revision = price.get("revision")
        if type(revision) is not int or revision < 0:
            raise InvalidRequest("Invalid assessment revision")
        name, cadence, max_age_hours = SYMBOLS[symbol]
        rows.append({"symbol": symbol, "name": name, "unit": "USD/cwt", "currency": "USD",
                     "prices": values, "usd_per_lb": {k: v / 100 for k, v in values.items()},
                     "assessment_date": observed.isoformat(), "revision": revision,
                     "assessment_age_seconds": max(0, age), "stale": age > max_age_hours * 3600,
                     "expected_cadence": cadence, "source_class": "physical_market_assessment",
                     "unit_basis": "US dollar per 100 lb, pinned series specification; verify entitlement/metadata before use"})
    return {"provider": "fastmarkets", "status": "ok", "observations": rows, "source_url": url,
            "response_sha256": digest,
            "limitation": "FOB-mill assessments, not delivered supplier offers or guaranteed fabricator costs. No automatic material-cost adoption."}


def lookup(request, env=None, fetch=fetch_json, now=None):
    request = validate(request)
    env = os.environ if env is None else env
    if env.get("KELLER_MARKET_ENABLED") != "1":
        return {"status": "disabled", "error": "Operator must enable market lookups", "http_attempts": 0}
    now = now or dt.datetime.now(dt.timezone.utc)
    attempts = 0

    def bounded_fetch(*args):
        nonlocal attempts
        attempts += 1
        if attempts > 5:
            raise InvalidRequest("HTTP call budget exhausted")
        return fetch(*args)

    def guarded(provider, action, key=None):
        if key is not None and not env.get(key):
            return {"provider": provider, "status": "not_configured", "error": "Provider credential not configured"}
        try:
            return action()
        except Exception:
            # Provider exceptions/URLs may contain credentials. Do not echo them.
            return {"provider": provider, "status": "unavailable", "error": "Lookup failed, timed out, exceeded bounds, or returned invalid data"}

    results = []
    for query in request["searches"]:
        results.append(guarded("exa", lambda q=query: search(q, env.get("EXA_API_KEY"), bounded_fetch), "EXA_API_KEY"))
    if request["include_bls"]:
        results.append(guarded("bls", lambda: bls_index(now, bounded_fetch)))
    if request["steel_symbols"]:
        if env.get("KELLER_FASTMARKETS_LICENSED") != "1":
            results.append({"provider": "fastmarkets", "status": "license_required",
                            "error": "Owner must confirm API, derived-pricing, display and AI-use rights"})
        else:
            results.append(guarded("fastmarkets", lambda: fastmarkets(request["steel_symbols"], env.get("FASTMARKETS_ACCESS_TOKEN"), now, bounded_fetch), "FASTMARKETS_ACCESS_TOKEN"))
    for result in results:
        result["captured_at"] = now.isoformat()
        result["supports_landed_cost"] = False
        result["requires_human_review"] = True
    success = sum(r["status"] == "ok" for r in results)
    return {"status": "ok" if success == len(results) else "partial" if success else "unavailable",
            "results": results, "http_attempts": attempts, "automatic_retries": 0,
            "next_cursor": None, "stop_reason": "bounded_batch_complete",
            "source_policy": "No automatic cost adoption, quote approval, customer release, or fallback to another provider."}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise InvalidRequest("Input exceeded byte budget")
        result = lookup(json.loads(raw))
    except Exception:
        result = {"error": "Invalid market lookup request"}
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
