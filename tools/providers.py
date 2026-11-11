"""Multi-provider LLM adapter.

Reads config/providers.json (model + the NAME of the env var holding its key) and .env
(the key values). Tries enabled providers in priority order, falling back to the next one
on quota / rate-limit / auth failure - which is what makes several free accounts useful.

Add a provider: add a block to config/providers.json, add its key to .env, set enabled=true.
On a fresh clone that file does not exist yet; paths.ensure_config() copies the committed
config/providers.example.json into place so there is always something to read.
"""
import json
import os
import re
import urllib.error
import urllib.request

import paths
import usage

ROOT = paths.ROOT
CONFIG = paths.ensure_config()

FALLBACK_STATUS = {401, 403, 429, 500, 502, 503, 504}


class AllProvidersFailed(RuntimeError):
    pass


def load_env():
    """Minimal .env reader - no dependency, and the file never leaves this machine."""
    path = paths.ENV
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, val = line.partition("=")
        os.environ.setdefault(k.strip(), val.strip().strip('"').strip("'"))


def enabled_providers():
    cfg = json.loads(CONFIG.read_text())["providers"]
    out = [(name, p) for name, p in cfg.items() if p.get("enabled")]
    return sorted(out, key=lambda kv: kv[1].get("priority", 99))


def _post(url, payload, headers):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 # Groq sits behind Cloudflare and 403s urllib's default User-Agent.
                 "User-Agent": "cvondemand/1.0", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def _tokens_gemini(data):
    m = data.get("usageMetadata") or {}
    return m.get("promptTokenCount", 0), m.get("candidatesTokenCount", 0)


def _tokens_openai(data):
    u = data.get("usage") or {}
    return u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _call_gemini(p, key, system, user, schema):
    url = f'{p["base_url"]}/models/{p["model"]}:generateContent?key={key}'
    gen = {"temperature": 0.2}
    if p.get("structured_output"):
        gen["response_mime_type"] = "application/json"
        gen["response_schema"] = schema
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }
    data = _post(url, body, {})
    return data["candidates"][0]["content"]["parts"][0]["text"], _tokens_gemini(data)


def _call_openai_compatible(p, key, system, user, schema):
    url = f'{p["base_url"]}/chat/completions'
    body = {
        "model": p["model"],
        "temperature": 0.2,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    if p.get("structured_output"):
        body["response_format"] = {"type": "json_object"}
    data = _post(url, body, {"Authorization": f"Bearer {key}"})
    return data["choices"][0]["message"]["content"], _tokens_openai(data)


CALLERS = {"gemini": _call_gemini, "openai_compatible": _call_openai_compatible}


def one_provider(name, model=None):
    """A single provider, optionally with its model overridden - for a deliberate dashboard pick."""
    cfg = json.loads(CONFIG.read_text())["providers"]
    if name not in cfg:
        raise ValueError(f"unknown provider: {name}")
    p = dict(cfg[name])
    if model:
        ids = [m["id"] for m in p.get("models", [])] or [p["model"]]
        if model not in ids:
            raise ValueError(f"model {model} is not in {name}'s list")
        p["model"] = model
    return [(name, p)]


def complete(system, user, schema, provider=None, model=None):
    """Try each enabled provider in priority order, or just `provider` when one is named.

    Returns (provider_name, parsed_json).
    """
    load_env()
    providers = one_provider(provider, model) if provider else enabled_providers()
    if not providers:
        raise AllProvidersFailed(
            "No provider is enabled. Set enabled=true for one in config/providers.json "
            "and put its key in .env (see .env.example).")

    errors = []
    for name, p in providers:
        key = os.environ.get(p["api_key_env"], "").strip()
        if not key:
            errors.append(f"{name}: {p['api_key_env']} is empty in .env")
            continue
        try:
            raw, (sent, got) = CALLERS[p["kind"]](p, key, system, user, schema)
            parsed = json.loads(_strip_fences(raw))
            usage.record(name, p["model"], True, sent, got)
            return name, parsed
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:200]
            usage.record(name, p["model"], False, error=f"HTTP {e.code} {detail}")
            errors.append(f"{name}: HTTP {e.code} {detail}")
            if e.code not in FALLBACK_STATUS:
                break
        except json.JSONDecodeError as e:
            # The call itself succeeded and burned quota - only the parse failed.
            usage.record(name, p["model"], False, error=f"bad JSON: {e}")
            errors.append(f"{name}: model did not return valid JSON ({e})")
        except Exception as e:  # noqa: BLE001 - report and try the next provider
            usage.record(name, p["model"], False, error=f"{type(e).__name__}: {e}")
            errors.append(f"{name}: {type(e).__name__}: {e}")

    raise AllProvidersFailed("All providers failed:\n  " + "\n  ".join(errors))


def _strip_fences(text):
    """Some models wrap JSON in ```json fences despite instructions."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t
