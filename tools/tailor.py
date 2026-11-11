"""Job description -> tailored cv.json, via an external strong model.

The model is deliberately given a NARROW surface: it may only propose wording and emphasis
for headline, summary, competencies, experience bullets, project descriptions and skill
ordering. Contact, employers, roles, dates, education, certificates, project titles and
order, and languages are merged back from master-cv.json and are unreachable by the model.
validate.py then checks what comes back before anything is rendered.
"""
import json

import paths
import providers

ROOT = paths.ROOT
TERMS = json.loads(paths.TERMS.read_text())

# Only these fields are model-writable.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "core_competencies": {"type": "ARRAY", "items": {"type": "STRING"}},
        "experience": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "company": {"type": "STRING"},
                    "bullets": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["company", "bullets"],
            },
        },
        "projects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "tech": {"type": "STRING"},
                },
                "required": ["title", "description", "tech"],
            },
        },
        "skills": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "items": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["label", "items"],
            },
        },
    },
    "required": ["headline", "summary", "core_competencies", "experience", "projects", "skills"],
}


PROMPT_MARKER = "<!-- PROMPT -->"


def canonical_names():
    """The canonical-name list as prompt text. Generated from terminology.json on purpose:
    validate.py enforces the same data mechanically, so a second prose copy would drift."""
    return ", ".join(f"{c} (never {'/'.join(v)})" for c, v in TERMS["canonical"].items())


def rules_text():
    """The editable rules from RULES.md - everything after the PROMPT marker. A file with no
    marker is sent whole, so deleting the marker degrades to noise, never to silence."""
    text = paths.RULES.read_text()
    _, marker, body = text.partition(PROMPT_MARKER)
    return (body if marker else text).strip()


def system_prompt():
    return f"""You are a strict JSON-generation engine that adapts one specific CV to one specific job description.

Output a single valid JSON object matching the given schema. No markdown fences, no commentary.

{rules_text()}

CANONICAL NAMES - use these spellings identically everywhere: {canonical_names()}."""


def user_prompt(master, jd, position):
    return f"""TARGET POSITION: {position}

JOB DESCRIPTION:
{jd}

MASTER CV (the only source of facts you may draw on):
{json.dumps(master, indent=2, ensure_ascii=False)}"""


def merge(master, proposal):
    """Apply the model's wording onto master. Immutable sections are copied, not taken."""
    cv = json.loads(json.dumps(master))  # deep copy

    cv["headline"] = proposal.get("headline") or master["headline"]
    cv["summary"] = proposal.get("summary") or master["summary"]
    if proposal.get("core_competencies"):
        cv["core_competencies"] = proposal["core_competencies"]

    bullets = {e.get("company"): e.get("bullets") for e in proposal.get("experience", [])}
    for job in cv["experience"]:                       # order and metadata stay master's
        if bullets.get(job["company"]):
            job["bullets"] = bullets[job["company"]]

    texts = {p.get("title"): p for p in proposal.get("projects", [])}
    for pr in cv["projects"]:                          # order and titles stay master's
        got = texts.get(pr["title"])
        if got:
            pr["description"] = got.get("description") or pr["description"]
            pr["tech"] = got.get("tech") or pr["tech"]

    groups = {g.get("label"): g.get("items") for g in proposal.get("skills", [])}
    for grp in cv["skills"]:                           # labels and group order stay master's
        if groups.get(grp["label"]):
            grp["items"] = groups[grp["label"]]

    return cv


def tailor(master, jd, position, extra_instructions="", provider=None, model=None):
    """provider/model name one specific model (the dashboard does); omit both for priority order."""
    user = user_prompt(master, jd, position)
    if extra_instructions:
        user += f"\n\nYOUR PREVIOUS ATTEMPT FAILED VALIDATION. Fix exactly these and return the full JSON again:\n{extra_instructions}"
    name, proposal = providers.complete(system_prompt(), user, RESPONSE_SCHEMA, provider, model)
    return name, merge(master, proposal)
