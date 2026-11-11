# cvondemand

One polished CV per target position. Your content lives in one place, a model proposes the
tailoring, a validator rejects anything it invented, and a renderer produces the `.docx` in a
format that cannot drift.

```
your CV  ->  intake.py (model)  ->  core/master-cv.json   (the only source of facts)
                                            |
job description  ->  tailor.py (model)  ->  validate.py  ->  render_cv.py  ->  .docx
                                                |
                                            fails? no .docx is written
```

The point is the gate. A model asked to tailor a CV will quietly add the technology the job
posting wants, round a number up, or promote you a title. `tools/validate.py` checks every
claim back against your master record and refuses to render anything it cannot find there.

## Quick start

```bash
git clone <this repo> && cd cvondemand
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
.venv/bin/python tools/dashboard.py          # opens http://127.0.0.1:8777
```

Then, in the dashboard:

1. **Providers** — paste an API key into one provider card and enable it. A free Google AI
   Studio key is enough. Keys are written to `.env` (gitignored, `chmod 600`) and never sent to
   the browser.
2. **Setup** — paste your existing CV, or upload it as a `.docx`. The model structures it and
   rewrites the prose professionally; your contact details are typed by hand, never guessed.
   Review what comes back, edit anything you like, save. That writes `core/master-cv.json`.
3. **Generate** — paste a job description, pick a position name, generate, review, save. You
   get `positions/<name>/cv.json` and a rendered `.docx` beside it.

Prefer the command line? Once a master exists:

```bash
# tailor to a new posting
.venv/bin/python tools/build.py "Full-Stack Developer (React.js, Node.js)" --jd ~/Desktop/jd.md

# re-validate and re-render an existing one (after editing master, rules or style)
.venv/bin/python tools/build.py "Full-Stack Developer (React.js, Node.js)"

# check any cv.json or .docx on its own
.venv/bin/python tools/validate.py "positions/<name>/cv.json"
```

No API key at all? Copy `core/master-cv.example.json` to `core/master-cv.json`, edit it by
hand, write `positions/<name>/cv.json` yourself, and run `build.py "<name>"` with no `--jd`.
The same gate applies either way.

## Your data stays yours

Nothing personal is tracked by git. These paths are all gitignored, and the repo ships an
`.example` file beside each one that needs a starting point:

| Gitignored | Committed example |
|---|---|
| `core/master-cv.json` — your facts and contact details | `core/master-cv.example.json` |
| `config/providers.json` — your model choices and key names | `config/providers.example.json` |
| `.env` — your key values | `.env.example` |
| `positions/` — every tailored CV, job description and `.docx` | — |
| `core/original/`, `imported/` — whatever you built the master from | — |

`config/providers.json` is created automatically from the example on first run, so a fresh
clone has something to edit.

## Tuning what the model writes

**`RULES.md` is a prompt.** `tools/tailor.py` and `tools/intake.py` read it at runtime and send
everything below its `PROMPT` marker to the model verbatim. Edit it and behaviour changes on
the next run — no code change. It ends with a *Your preferences* section meant to be rewritten.

Two kinds of rule, and it matters which is which:

- **Prose rules** live in `RULES.md` and are enforced by asking the model nicely.
- **Mechanical rules** live in `config/terminology.json` and are enforced by `validate.py`,
  which blocks the render. Canonical names, protected phrases, the forbidden-string list and
  the hyphenation noun list are all data here — add to the JSON rather than describing them in
  prose, or the two copies will drift.

## Adding or editing models and API keys

Everything lives in **`config/providers.json`** (created from
`config/providers.example.json`). Keys themselves never go in that file — it stores only the
*name* of the environment variable that holds each key. Values go in `.env`.

To add a provider:

1. Add a block to `config/providers.json`:
   ```jsonc
   "my_provider": {
     "label": "Whatever you call it",
     "kind": "gemini",            // or "openai_compatible"
     "base_url": "https://...",
     "model": "model-id",
     "api_key_env": "MY_PROVIDER_KEY",   // the NAME, not the key
     "structured_output": true,
     "priority": 5,               // lower numbers are tried first
     "enabled": true
   }
   ```
2. Add `MY_PROVIDER_KEY=...` to `.env`, or paste the key into that provider's card in the
   dashboard.
3. Done. `providers.py` tries enabled providers in priority order and falls back to the next
   one on quota, rate-limit or auth failure — which is what makes several free accounts useful.

`kind` is either `gemini` (Google AI Studio) or `openai_compatible` (Groq, OpenRouter,
Together, and most others). Blocks for Groq and OpenRouter ship disabled.

**On `.docx` from a model:** the AI Studio API is text-only and cannot return a binary file, so
the model always returns JSON. This is the better path anyway — Gemini enforces our schema at
the API level via `response_schema`, rather than being asked politely in a prompt.

## Layout

| Path | What it is |
|---|---|
| `RULES.md` | **The editable prompt.** Writing rules, read at runtime |
| `core/master-cv.json` | **The only source of facts.** Nothing may be claimed that is not here |
| `core/master-cv.example.json` | A fictional persona, so a fresh clone runs end to end |
| `config/providers.json` | Models and key names — see above |
| `config/terminology.json` | Canonical tech names, protected phrases, hyphenation rules |
| `config/style.json` | Locked page geometry and fonts |
| `tools/paths.py` | Shared paths and first-run bootstrap |
| `tools/intake.py` | Your CV → a structured, validated master |
| `tools/tailor.py` | Master + job description → a tailored proposal |
| `tools/validate.py` | The gate |
| `tools/render_cv.py` | `cv.json` → `.docx`, section order hardcoded |
| `tools/build.py` | The command-line orchestrator |
| `tools/dashboard.py` | The local web dashboard, localhost only |
| `positions/<name>/` | `cv.json`, `NOTES.md`, `job-descriptions/`, and the built `.docx` |

## What the validator enforces

1. **Schema** — all nine locked sections present and well-formed.
2. **Facts** — every employer, role, date, degree, certificate, project and technology must
   already exist in `core/master-cv.json`. Invented skills and trendy technologies the CV does
   not have are rejected by name.
3. **Order** — projects, skill groups and experience entries stay in master order. Skill items
   may be reordered and dropped, never added.
4. **Terminology** — canonical names (`React.js`, not `ReactJS` or bare `React`), protected
   phrases (`Tailwind CSS` can never become `Tailwind CSS3`), and hyphenation
   (`front-end components` but `on the front end`).

At intake there is no master to compare against yet, so `tools/intake.py` substitutes its own
guard: any technology in the drafted master that does not appear in the CV you supplied is
reported, and the save is refused until it is gone.

Run the validator against any file to see what it catches.
