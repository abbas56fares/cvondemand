"""Raw CV (pasted text or an uploaded .docx) -> a validated core/master-cv.json.

This is the one step that creates facts rather than rewording them, so it is the one step
where fabrication can enter the system. Three things hold it down:

  * contact details are typed by the user, never extracted - a hallucinated digit in a phone
    number is invisible and unrecoverable, and render_cv.py turns email and phone into live
    mailto:/tel: links;
  * the model is told to carry every employer, date, degree, certificate and technology across
    verbatim and to reword only the prose around them;
  * unsupported_terms() then checks the draft back against the raw source and reports any
    technology that appears in the draft but not in what the user actually supplied. The normal
    factual guard cannot run here - there is no master yet to compare against.

RULES.md is shared with tailor.py, so the professional rewrite and the later tailoring cannot
disagree about tone.
"""
import io
import json
import re

import paths
import providers
import tailor as tailor_mod
import validate as validate_mod

TERMS = json.loads(paths.TERMS.read_text())

CONTACT_FIELDS = ("name", "nationality", "address", "email", "phone")

# The full master shape minus contact, which the user types.
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
                    "role": {"type": "STRING"},
                    "company": {"type": "STRING"},
                    "dates": {"type": "STRING"},
                    "bullets": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["role", "company", "dates", "bullets"],
            },
        },
        "education": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "degree": {"type": "STRING"},
                    "institution": {"type": "STRING"},
                    "date": {"type": "STRING"},
                },
                "required": ["degree", "institution", "date"],
            },
        },
        "certificates": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "issuer": {"type": "STRING"},
                    "date": {"type": "STRING"},
                },
                "required": ["name", "issuer", "date"],
            },
        },
        "projects": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "date": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "tech": {"type": "STRING"},
                },
                "required": ["title", "date", "description", "tech"],
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
        "languages": {"type": "STRING"},
    },
    "required": ["headline", "summary", "core_competencies", "experience", "education",
                 "certificates", "projects", "skills", "languages"],
}


def system_prompt():
    return f"""You are a strict JSON-generation engine that turns one person's existing CV into
the structured master record this tool runs on.

Output a single valid JSON object matching the given schema. No markdown fences, no commentary.

WHAT THIS STEP IS

The user has supplied their real CV as raw text. Your job is to STRUCTURE and POLISH it, not to
rewrite their career. Carry every fact across; improve only the words around the facts.

CARRY ACROSS VERBATIM - these are facts, not prose:
  * every employer name, job title and set of dates, in the order the source gives them
  * every degree, institution and graduation date
  * every certificate, its issuer and its date
  * every project title and date
  * every technology named anywhere in the source
  * the languages the person speaks and the level claimed for each

POLISH FREELY - these are prose:
  * the headline and the professional summary
  * each experience bullet
  * each project description
  * the core competencies list

If the source has no summary, no headline, or no core competencies, write them FROM the facts
that are present. That is composition from supplied material, not invention.

STRUCTURE NOTES

  * Group skills into labelled groups that fit what the person actually has. Use the source's
    own grouping if it has one. A sensible default is: frontend, backend, programming
    languages, databases, tools and DevOps, soft skills. Omit a group the person has nothing
    for - never pad one out.
  * "tech" on a project is a single string listing the stack, e.g.
    "Frontend: React.js, Backend: Node.js, Express.js, Database: PostgreSQL."
  * "languages" is a single string, e.g. "Arabic (native), English (professional working
    proficiency)."
  * Dates stay in the format the source uses. Do not reformat or infer a missing one.

HARD LIMIT ON INVENTION

Do not add a technology, employer, responsibility, certificate, metric or percentage that is
absent from the supplied CV. If the source is thin, the master is thin - that is correct and
recoverable. An invented fact is neither. Do not infer a skill from a job title. Do not add a
number to make a bullet sound measurable.

{tailor_mod.rules_text()}

CANONICAL NAMES - normalise every technology you carry across to these spellings:
{tailor_mod.canonical_names()}."""


def user_prompt(raw):
    return f"""THE PERSON'S EXISTING CV, VERBATIM:

{raw}"""


def raw_from_docx(data):
    """Bytes of a .docx -> its text, via validate.docx_text and no temporary file."""
    return validate_mod.docx_text(io.BytesIO(data))


def draft(raw, contact, provider=None, model=None):
    """raw: the CV as text. contact: the hand-typed contact block. Returns (provider, master)."""
    name, proposal = providers.complete(
        system_prompt(), user_prompt(raw), RESPONSE_SCHEMA, provider, model
    )
    master = {"contact": contact}
    master.update(proposal)
    return name, master


def unsupported_terms(master, raw):
    """Technologies the draft claims that the raw source never mentioned. The intake-time
    stand-in for check_facts, which needs a master to compare against and so cannot run yet."""
    canon = list(TERMS["canonical"]) + TERMS.get("known_technologies", [])
    in_source = validate_mod._tech_vocab(raw, canon)
    violations = []
    for field, text in validate_mod.prose_of(master):
        for t in sorted(validate_mod._tech_vocab(text, canon) - in_source):
            violations.append(
                f"FACT    {t!r} in {field} does not appear in the CV you supplied - "
                f"remove it, or add it to your CV text and draft again"
            )
    return violations


def clean_contact(payload):
    """Validate and normalise the typed contact block. Raises ValueError on anything missing."""
    contact = {}
    for key in CONTACT_FIELDS:
        value = (payload.get(key) or "").strip()
        if not value and key in ("name", "email", "phone"):
            raise ValueError(f"contact.{key} is required - it goes in the CV header")
        contact[key] = value

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", contact["email"]):
        raise ValueError(f"{contact['email']!r} does not look like an email address")

    links = []
    for link in payload.get("links") or []:
        label = (link.get("label") or "").strip()
        url = (link.get("url") or "").strip()
        if not label and not url:
            continue
        if not label or not url:
            raise ValueError("every link needs both a label and a URL")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"link {label!r} must start with http:// or https://")
        links.append({"label": label, "url": url})
    if not links:
        raise ValueError("add at least one link - the CV header expects one")
    contact["links"] = links
    return contact


def check(master, raw):
    """Everything that can be checked before a master exists: schema, terminology, and the
    source-support guard. check_facts is deliberately absent - it needs a master."""
    # The draft is its own master here, so its institutions and employers protect themselves.
    return (validate_mod.check_schema(master)
            + validate_mod.check_terminology(master, master)
            + unsupported_terms(master, raw))
