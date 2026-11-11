"""Tiny local dashboard: provider settings, and tailoring a CV from a job description.

    .venv/bin/python tools/dashboard.py        # then open http://127.0.0.1:8777

Settings half reads and writes config/providers.json (model choice, enabled flag) and .env
(key values). Generate half posts a position + job description to one chosen model, shows
what came back with the validation verdict, and writes cv.json + the .docx only when asked.

Binds to localhost only. Keys are never sent to the browser - only whether one is set and
its last four characters. fal.ai (video/) is a separate platform and is deliberately absent.
"""
import base64
import json
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intake as intake_mod
import paths
import providers
import render_cv
import tailor as tailor_mod
import usage as usage_mod
import validate as validate_mod

ROOT = paths.ROOT
MASTER = paths.MASTER
POSITIONS = paths.POSITIONS
CONFIG = paths.ensure_config()
ENV = paths.ENV
PAGE = Path(__file__).resolve().parent / "dashboard.html"
HOST, PORT = "127.0.0.1", 8777


def read_config():
    return json.loads(CONFIG.read_text())


def write_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def read_env():
    """Parse .env into a dict. Missing file is simply an empty environment."""
    values = {}
    if not ENV.exists():
        return values
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def write_env_var(name, value):
    """Update one variable in .env, leaving every other line untouched."""
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    pattern = re.compile(rf"^\s*#?\s*{re.escape(name)}\s*=")
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    ENV.write_text("\n".join(lines).strip() + "\n")
    os.chmod(ENV, 0o600)


def mask(value):
    if not value:
        return ""
    return "•" * 8 + value[-4:]


def state():
    cfg = read_config()
    env = read_env()
    out = []
    for name, p in sorted(cfg["providers"].items(), key=lambda kv: kv[1].get("priority", 99)):
        key = env.get(p["api_key_env"], "")
        out.append({
            "name": name,
            "label": p["label"],
            "kind": p["kind"],
            "priority": p.get("priority", 99),
            "enabled": bool(p.get("enabled")),
            "model": p["model"],
            "models": p.get("models", [{"id": p["model"], "status": "ok", "description": ""}]),
            "api_key_env": p["api_key_env"],
            "key_set": bool(key),
            "key_masked": mask(key),
        })
    existing = sorted(d.name for d in POSITIONS.iterdir() if d.is_dir()) if POSITIONS.exists() else []
    have_master = paths.master_exists()
    return {
        "providers": out,
        "positions": existing,
        "master_exists": have_master,
        "needs_setup": not have_master,
        "contact": json.loads(MASTER.read_text()).get("contact", {}) if have_master else {},
    }


def require_master():
    """Everything except Setup needs a master. Say so plainly instead of dying on a read."""
    if not paths.master_exists():
        raise ValueError(
            "No master CV yet. Open the Setup tab and paste your CV first - everything else "
            "reads from core/master-cv.json."
        )
    return json.loads(MASTER.read_text())


def draft_master(payload):
    """Raw CV -> a drafted master, checked but NOT written. Mirrors run_tailor's contract."""
    contact = intake_mod.clean_contact(payload.get("contact") or {})
    raw = (payload.get("raw") or "").strip()
    if payload.get("docx_b64"):
        try:
            raw = (raw + "\n\n" + intake_mod.raw_from_docx(
                base64.b64decode(payload["docx_b64"]))).strip()
        except Exception as e:  # noqa: BLE001 - a bad upload is the user's problem to see
            raise ValueError(f"could not read that .docx: {type(e).__name__}: {e}") from e
    if len(raw) < 80:
        raise ValueError("Paste your CV text or upload a .docx - there is too little to work from.")

    provider = (payload.get("provider") or "").strip()
    if not provider:
        raise ValueError("Pick a provider.")

    used, master = intake_mod.draft(raw, contact, provider, (payload.get("model") or "").strip())
    return {
        "provider": used,
        "master": master,
        "violations": intake_mod.check(master, raw),
        "raw": raw,          # handed back so save-master can re-run the source-support check
        "raw_chars": len(raw),
    }


def save_master(payload):
    """Write core/master-cv.json - gated, and refusing to clobber silently."""
    master = payload.get("master")
    raw = (payload.get("raw") or "").strip()
    if not isinstance(master, dict):
        raise ValueError("Nothing to save - draft a master CV first.")
    if paths.master_exists() and not payload.get("overwrite"):
        raise ValueError(
            "core/master-cv.json already exists. Re-send with overwrite to replace it; "
            "your positions and their cv.json files are untouched either way."
        )

    violations = intake_mod.check(master, raw) if raw else (
        validate_mod.check_schema(master) + validate_mod.check_terminology(master, master))
    if violations:
        raise ValueError("Validation failed, nothing written:\n" + "\n".join(violations))

    MASTER.parent.mkdir(parents=True, exist_ok=True)
    MASTER.write_text(json.dumps(master, indent=2, ensure_ascii=False) + "\n")
    return {"saved": os.path.relpath(MASTER, ROOT), "state": state()}


def usage_snapshot():
    """Ledger counts and declared limits for every provider and model. No network, so the
    page can poll this as often as it likes."""
    return usage_mod.snapshot(env=read_env())


def usage_probe(payload):
    """Ask ONE provider for its real numbers. Separate from the snapshot on purpose: a Groq
    probe spends a request, so it must never fire just because the page loaded."""
    cfg = read_config()
    name = payload.get("provider")
    if name not in cfg["providers"]:
        raise ValueError(f"unknown provider: {name}")
    p = cfg["providers"][name]
    model = (payload.get("model") or "").strip() or p["model"]
    ids = [m["id"] for m in p.get("models", [])] or [p["model"]]
    if model not in ids:
        raise ValueError(f"model {model} is not in {name}'s list")
    key = read_env().get(p["api_key_env"], "").strip()
    result = usage_mod.probe(name, p, key, model)
    return {"provider": name, "model": model, "probe": result}


def save(payload):
    """Apply a dashboard edit. Only the fields present in the payload are touched."""
    cfg = read_config()
    name = payload.get("name")
    if name not in cfg["providers"]:
        raise ValueError(f"unknown provider: {name}")
    p = cfg["providers"][name]

    if "model" in payload:
        ids = [m["id"] for m in p.get("models", [])] or [p["model"]]
        if payload["model"] not in ids:
            raise ValueError(f"model {payload['model']} is not in this provider's list")
        p["model"] = payload["model"]

    if "enabled" in payload:
        p["enabled"] = bool(payload["enabled"])

    key = (payload.get("api_key") or "").strip()
    if key:
        write_env_var(p["api_key_env"], key)

    if p["enabled"] and not read_env().get(p["api_key_env"], ""):
        p["enabled"] = False
        write_config(cfg)
        raise ValueError(f"{p['api_key_env']} is empty - add a key before enabling {p['label']}")

    write_config(cfg)
    return state()


def run_tailor(payload):
    """Call one chosen model, validate the result, and hand both back. Writes nothing."""
    position = (payload.get("position") or "").strip()
    jd = (payload.get("jd") or "").strip()
    provider = (payload.get("provider") or "").strip()
    model = (payload.get("model") or "").strip()
    if not position:
        raise ValueError("Position name is required.")
    if not jd:
        raise ValueError("Job description is required.")
    if not provider:
        raise ValueError("Pick a provider.")
    if "/" in position or position.startswith("."):
        raise ValueError("Position name cannot contain '/' or start with '.'")

    master = require_master()
    used, cv = tailor_mod.tailor(master, jd, position, provider=provider, model=model)
    return {
        "provider": used,
        "model": model,
        "position": position,
        "cv": cv,
        "violations": validate_mod.validate(cv, master),
    }


def run_build(payload):
    """Save the reviewed cv.json (plus the job description) and render the .docx - gated."""
    position = (payload.get("position") or "").strip()
    cv = payload.get("cv")
    jd = payload.get("jd") or ""
    if not position or "/" in position or position.startswith("."):
        raise ValueError("A valid position name is required.")
    if not isinstance(cv, dict):
        raise ValueError("Nothing to save - generate a CV first.")

    master = require_master()
    violations = validate_mod.validate(cv, master)
    if violations:
        raise ValueError("Validation failed, nothing written:\n" + "\n".join(violations))

    folder = POSITIONS / position
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cv.json").write_text(json.dumps(cv, indent=2, ensure_ascii=False) + "\n")
    if jd.strip():
        jds = folder / "job-descriptions"
        jds.mkdir(exist_ok=True)
        (jds / "jd-from-dashboard.md").write_text(jd)

    out = folder / render_cv.output_name(cv, position)
    render_cv.build(cv, out)
    return {"saved": str(out.relative_to(ROOT)), "positions": state()["positions"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path.startswith("/api/usage"):
                self._send(200, json.dumps(usage_snapshot()))
            elif self.path.startswith("/api/state"):
                self._send(200, json.dumps(state()))
            elif self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(404, json.dumps({"error": "not found"}))
        except Exception as e:  # noqa: BLE001 - a dashboard must not die on one bad request
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if self.path.startswith("/api/probe"):
                self._send(200, json.dumps(usage_probe(payload)))
            elif self.path.startswith("/api/draft-master"):
                self._send(200, json.dumps(draft_master(payload)))
            elif self.path.startswith("/api/save-master"):
                self._send(200, json.dumps(save_master(payload)))
            elif self.path.startswith("/api/save-cv"):
                self._send(200, json.dumps(run_build(payload)))
            elif self.path.startswith("/api/save"):
                self._send(200, json.dumps(save(payload)))
            elif self.path.startswith("/api/tailor"):
                self._send(200, json.dumps(run_tailor(payload)))
            else:
                self._send(404, json.dumps({"error": "not found"}))
        except ValueError as e:
            self._send(400, json.dumps({"error": str(e)}))
        except providers.AllProvidersFailed as e:
            # The model was unreachable - the user's own fault to retry, not a server bug.
            self._send(502, json.dumps({"error": str(e)}))
        except Exception as e:  # noqa: BLE001
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))


def main():
    url = f"http://{HOST}:{PORT}"
    print(f"cvondemand dashboard -> {url}   (ctrl-c to stop)")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - opening a browser is a convenience, not a requirement
        pass
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
