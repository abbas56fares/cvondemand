# cvondemand — rules for this project

A CV engine: one tailored, validated CV per target position, all of it generated from a single
master record the user owns.

## Hard rules

1. **Never invent.** Every employer, role, date, degree, certificate, project and technology
   must already exist in `core/master-cv.json`. Tailoring means rewording and re-emphasising,
   never adding. If a job asks for a skill the person does not have, say so — do not claim it.
   `core/master-cv.json` is the only place a new fact may enter, and only the user may put one
   there (by hand, or through the dashboard's Setup tab).

2. **Never change the layout or the order.** Section order is fixed in `tools/render_cv.py`:
   Summary → Core Competencies → Professional Experience → Education → Training and
   Certificates → Projects → Skills → Languages. Project order, skill-group order and
   experience order all stay as in master. `tools/validate.py` blocks this mechanically — do
   not work around it.

3. **No `.docx` without validation.** Always go through `tools/build.py` or the dashboard. The
   gate will not render content that fails.

4. **Never commit or print API keys.** `.env` holds values and is gitignored.
   `config/providers.json` holds only env-var names, and is itself gitignored — the committed
   file is `config/providers.example.json`.

5. **Writing rules live in `RULES.md`, not in code.** It is read at runtime by
   `tools/tailor.py` and `tools/intake.py` and sent to the model verbatim. Change behaviour by
   editing that file. Canonical names, protected phrases and the hyphenation noun list are
   data in `config/terminology.json`, enforced mechanically by `tools/validate.py` — never
   restate them as prose, or the two copies will drift.

## What is personal and must never be committed

These are gitignored. Keep it that way, and do not add a new file holding personal data
without ignoring it in the same change.

| Path | |
|---|---|
| `core/master-cv.json`, `core/master-cv.md` | the facts, including contact details |
| `core/original/` | whatever the master was built from |
| `positions/` | every tailored `cv.json`, `NOTES.md`, job description and built `.docx` |
| `imported/` | harvested CV variants |
| `config/providers.json` | model choices and key names |
| `.env` | key values |
| `CLAUDE.local.md` | machine-specific notes |

## Normal workflow

First run, or replacing the master:

```bash
.venv/bin/python tools/dashboard.py     # Setup tab -> paste or upload a CV -> review -> save
```

New job description arrives:

```bash
.venv/bin/python tools/build.py "<Position Name>" --jd <path>
```

If no position fits, create a new folder under `positions/` named by role and stack, e.g.
`Full-Stack Developer (React.js, Node.js)`.

Without an API key configured, write `positions/<name>/cv.json` by hand and run
`tools/build.py "<name>"` with no `--jd`; the same gate applies either way.

## Known failure modes worth remembering

- `front end` / `back end` are nouns; `front-end` / `back-end` are modifiers. This is the most
  frequently broken rule, including by models explicitly told the rule.
- A blind `CSS` → `CSS3` rewrite corrupts `Tailwind CSS` into `Tailwind CSS3`. This has
  happened; `config/terminology.json` has a `protected` list guarding against it.
- `known_technologies` in `config/terminology.json` is a **denylist** of technologies the master
  does *not* claim. `validate.py` drops from it anything the master genuinely has, so never
  treat it as a skill list.
- python-docx needs `WD_TAB_ALIGNMENT.RIGHT` for right tab stops, not `WD_ALIGN_PARAGRAPH.RIGHT`,
  and has no hyperlink API — `render_cv.py` has an `add_hyperlink()` helper.
