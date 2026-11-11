"""Usage ledger and provider limit probes - the data behind the dashboard's limit bars.

Two independent sources answer "how much of this key have I used?":

  local ledger   state/usage.jsonl, one line per call this tool made, appended by
                 providers.complete(). Always available and free to read, but it only
                 ever sees traffic from this machine - a call you made from another
                 script or the provider's own playground is invisible to it.

  remote probe   the provider's own numbers, for the providers that have any. Checked
                 against the live APIs rather than assumed:
                   groq        x-ratelimit-* headers on a completion - real limit AND
                               remaining, per model, but reading them costs one request.
                   openrouter  GET /key - credits spent against the credit cap.
                   gemini      nothing. Google AI Studio publishes no quota endpoint
                               for an API key, so Gemini rows stay on the ledger and
                               the limits declared in config/providers.json.

Which probe a provider uses is declared by its "usage_probe" field, never guessed.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import paths

ROOT = paths.ROOT
CONFIG = paths.ensure_config()
LEDGER = paths.LEDGER

MINUTE = 60
PROBE_TIMEOUT = 20

# Rows older than this are ignored when the ledger is read. A limit bar never looks
# further back than a day; the extra week is only so "calls so far" means something.
# The file itself is one short line per call, so it is left to grow.
KEEP_SECONDS = 60 * 60 * 24 * 7


# ───────────────────────── ledger ─────────────────────────

def record(provider, model, ok, prompt_tokens=0, completion_tokens=0, error=None):
    """Append one call to the ledger. Never raises - a bookkeeping failure must not
    break a CV that was generated successfully."""
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "at": time.time(),
            "provider": provider,
            "model": model,
            "ok": bool(ok),
            "prompt": int(prompt_tokens or 0),
            "completion": int(completion_tokens or 0),
        }
        if error:
            row["error"] = str(error)[:200]
        with LEDGER.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 - bookkeeping is best-effort by design
        pass


def _read_ledger():
    if not LEDGER.exists():
        return []
    rows = []
    cutoff = time.time() - KEEP_SECONDS
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written line from a killed process
        if row.get("at", 0) >= cutoff:
            rows.append(row)
    return rows


def _day_start():
    """Local midnight. Most free tiers reset on the provider's own clock, not yours -
    the dashboard says 'today (local)' so the number is never mistaken for theirs."""
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def local_counts():
    """{(provider, model): counters} from our own ledger."""
    rows = _read_ledger()
    now = time.time()
    minute_start, day_start = now - MINUTE, _day_start()
    out = {}
    for row in rows:
        key = (row.get("provider"), row.get("model"))
        c = out.setdefault(key, {
            "rpm": 0, "tpm": 0, "rpd": 0, "tpd": 0,
            "requests_total": 0, "tokens_total": 0, "failures": 0, "last_used": None,
        })
        tokens = row.get("prompt", 0) + row.get("completion", 0)
        at = row.get("at", 0)
        c["requests_total"] += 1
        c["tokens_total"] += tokens
        if not row.get("ok"):
            c["failures"] += 1
        if at >= day_start:
            c["rpd"] += 1
            c["tpd"] += tokens
        if at >= minute_start:
            c["rpm"] += 1
            c["tpm"] += tokens
        if c["last_used"] is None or at > c["last_used"]:
            c["last_used"] = at
    return out


# ───────────────────────── limits ─────────────────────────

def limits_for(provider, model_entry):
    """Model-level limits win over the provider default. Absent means unknown, which
    is reported honestly rather than filled with a guess."""
    merged = dict(provider.get("limits") or {})
    merged.update(model_entry.get("limits") or {})
    return {k: v for k, v in merged.items() if isinstance(v, (int, float)) and v > 0}


BAR_LABELS = {
    "rpm": ("Requests / min", "rpm"),
    "tpm": ("Tokens / min", "tpm"),
    "rpd": ("Requests today", "rpd"),
    "tpd": ("Tokens today", "tpd"),
}


def _bars(counts, limits):
    """One bar per limit the provider actually has a number for."""
    bars = []
    for key, (label, field) in BAR_LABELS.items():
        if key not in limits:
            continue
        limit = limits[key]
        used = counts.get(field, 0)
        bars.append({
            "key": key,
            "label": label,
            "used": used,
            "limit": limit,
            "pct": min(100, round(used / limit * 100, 1)) if limit else 0,
        })
    return bars


# ───────────────────────── remote probes ─────────────────────────

def _request(url, headers, payload=None, method="GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json",
                 # Groq sits behind Cloudflare and 403s urllib's default User-Agent.
                 "User-Agent": "cvondemand/1.0", **headers})
    with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as r:
        body = r.read().decode()
        return dict(r.headers), (json.loads(body) if body.strip() else {})


def _parse_reset(text):
    """Groq writes resets as '1m26.4s', '547ms', '2h30m'. Returns seconds, or None."""
    if not text:
        return None
    total, found = 0.0, False
    for value, unit in re.findall(r"([\d.]+)\s*(ms|s|m|h|d)", str(text)):
        found = True
        total += float(value) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return round(total, 1) if found else None


def _probe_groq_headers(provider, key, model):
    """Groq reports limit and remaining in headers, but only on a real completion -
    GET /models carries none (checked). So this spends one request and one token."""
    headers, _ = _request(
        f'{provider["base_url"]}/chat/completions',
        {"Authorization": f"Bearer {key}"},
        {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "."}]},
        method="POST")

    def num(name):
        raw = headers.get(name)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    bars, windows = [], [
        ("rpd", "Requests", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
         "x-ratelimit-reset-requests"),
        ("tpm", "Tokens", "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
         "x-ratelimit-reset-tokens"),
    ]
    for bar_key, label, limit_h, remaining_h, reset_h in windows:
        limit, remaining = num(limit_h), num(remaining_h)
        if limit is None or remaining is None:
            continue
        used = max(0, limit - remaining)
        reset = _parse_reset(headers.get(reset_h))
        bars.append({
            "key": bar_key,
            "label": f"{label} (window)",
            "used": int(used),
            "limit": int(limit),
            "pct": min(100, round(used / limit * 100, 1)) if limit else 0,
            "resets_in": reset,
        })
    if not bars:
        return {"supported": False, "reason": "Groq returned no x-ratelimit-* headers."}
    return {"supported": True, "scope": "model", "bars": bars,
            "note": "Live from Groq's x-ratelimit headers for this model. Reading them costs one request."}


def _probe_openrouter_key(provider, key, model):
    """GET /key is free and reports credits spent against the cap - account-wide, so
    the same numbers apply to every model on the key."""
    _, body = _request(f'{provider["base_url"]}/key', {"Authorization": f"Bearer {key}"})
    data = body.get("data", body)
    usage, limit = data.get("usage"), data.get("limit")
    bars = []
    if isinstance(usage, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        bars.append({
            "key": "credits", "label": "Credits used ($)",
            "used": round(usage, 4), "limit": round(limit, 4),
            "pct": min(100, round(usage / limit * 100, 1)),
        })
    detail = []
    if isinstance(usage, (int, float)):
        detail.append(f"${usage:.4f} spent")
    if limit is None:
        detail.append("no credit cap on this key")
    if data.get("is_free_tier"):
        detail.append("free tier")
    rate = data.get("rate_limit") or {}
    if rate.get("requests"):
        detail.append(f'{rate["requests"]} requests / {rate.get("interval", "?")}')
    note = "Live from OpenRouter GET /key, account-wide."
    if detail:
        note += " " + ", ".join(detail) + "."
    return {"supported": True, "scope": "account", "bars": bars, "note": note}


PROBES = {
    "groq_headers": _probe_groq_headers,
    "openrouter_key": _probe_openrouter_key,
}

NO_PROBE_REASON = {
    "gemini_none": "Google AI Studio has no quota endpoint for an API key, so there is "
                   "nothing to read. The bar counts calls made from this tool against "
                   "the limits declared in config/providers.json - edit them to match "
                   "your own console.",
}


def probe(name, provider, key, model=None):
    """Ask one provider for its real numbers. Returns {supported, bars, note|reason}."""
    which = provider.get("usage_probe", "none")
    if which in PROBES:
        if not key:
            return {"supported": False,
                    "reason": f'{provider["api_key_env"]} is empty - add a key first.'}
        model = model or provider["model"]
        try:
            return PROBES[which](provider, key, model)
        except urllib.error.HTTPError as e:
            return {"supported": False,
                    "reason": f"HTTP {e.code} from {name}: {e.read().decode()[:160]}"}
        except Exception as e:  # noqa: BLE001 - a dead probe must not break the page
            return {"supported": False, "reason": f"{type(e).__name__}: {e}"}
    return {"supported": False,
            "reason": NO_PROBE_REASON.get(which, "No usage API for this provider.")}


# ───────────────────────── assembled view ─────────────────────────

def snapshot(env=None):
    """Every provider and model with its ledger counts and declared limits. No network."""
    cfg = json.loads(CONFIG.read_text())["providers"]
    env = env if env is not None else os.environ
    counts = local_counts()
    day_start = _day_start()

    rows = []
    for name, p in sorted(cfg.items(), key=lambda kv: kv[1].get("priority", 99)):
        models = p.get("models") or [{"id": p["model"], "status": "ok"}]
        model_rows = []
        for m in models:
            c = counts.get((name, m["id"]), {})
            limits = limits_for(p, m)
            model_rows.append({
                "id": m["id"],
                "status": m.get("status", "ok"),
                "selected": m["id"] == p["model"],
                "local": {
                    "rpm": c.get("rpm", 0), "tpm": c.get("tpm", 0),
                    "rpd": c.get("rpd", 0), "tpd": c.get("tpd", 0),
                    "requests_total": c.get("requests_total", 0),
                    "tokens_total": c.get("tokens_total", 0),
                    "failures": c.get("failures", 0),
                    "last_used": c.get("last_used"),
                },
                "limits": limits,
                "limit_source": "declared" if limits else "unknown",
                "bars": _bars(c, limits),
            })
        rows.append({
            "name": name,
            "label": p["label"],
            "enabled": bool(p.get("enabled")),
            "key_set": bool(str(env.get(p["api_key_env"], "")).strip()),
            "probe": p.get("usage_probe", "none"),
            "probe_live": p.get("usage_probe", "none") in PROBES,
            "probe_cost": "one request and one token" if p.get("usage_probe") == "groq_headers" else "free",
            "models": model_rows,
            "totals": {
                "rpd": sum(m["local"]["rpd"] for m in model_rows),
                "tpd": sum(m["local"]["tpd"] for m in model_rows),
                "requests_total": sum(m["local"]["requests_total"] for m in model_rows),
            },
        })
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "day_start": day_start, "providers": rows}
