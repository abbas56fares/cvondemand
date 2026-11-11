"""THE GATE. No .docx is ever produced from content that fails this.

Three layers:
  1. schema        - all nine locked sections present and well-formed
  2. factual guard - nothing exists in the candidate that is absent from master-cv.json
  3. terminology   - canonical names, protected phrases, hyphenation

Usage:
    validate.py <candidate.json|candidate.docx> [--master core/master-cv.json]
Exit 0 = PASS, exit 1 = violations found (printed one per line).
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import paths

ROOT = paths.ROOT
TERMS = json.loads(paths.TERMS.read_text())
STYLE = json.loads(paths.STYLE.read_text())

# Not followed by a word char, and not followed by ".<word char>" - so "TypeScript." matches
# at end of sentence while "React" inside "React.js" still does not.
RB = r"(?![\w])(?!\.\w)"
LB = r"(?<![\w.])"

REQUIRED = ["contact", "headline", "summary", "core_competencies", "experience",
            "education", "certificates", "projects", "skills", "languages"]


# ---------- input ----------

def docx_text(source):
    """source is a path or any file object - zipfile accepts both, so an uploaded .docx can
    be read straight from a BytesIO without touching the disk."""
    xml = zipfile.ZipFile(source).read("word/document.xml").decode("utf-8")
    xml = re.sub(r"<w:tab[ /][^>]*>|<w:tab/>", " ", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return (xml.replace("&amp;", "&").replace("&lt;", "<")
               .replace("&gt;", ">").replace("&quot;", '"').replace("&#8217;", "’"))


def prose_of(cv):
    """Every piece of free text in a cv dict, as (field_path, text) pairs."""
    out = [("headline", cv.get("headline", "")), ("summary", cv.get("summary", ""))]
    for i, c in enumerate(cv.get("core_competencies", [])):
        out.append((f"core_competencies[{i}]", c))
    for i, job in enumerate(cv.get("experience", [])):
        for k in ("role", "company", "dates"):
            out.append((f"experience[{i}].{k}", job.get(k, "")))
        for j, b in enumerate(job.get("bullets", [])):
            out.append((f"experience[{i}].bullets[{j}]", b))
    for i, p in enumerate(cv.get("projects", [])):
        for k in ("title", "description", "tech"):
            out.append((f"projects[{i}].{k}", p.get(k, "")))
    for i, s in enumerate(cv.get("skills", [])):
        out.append((f"skills[{i}].label", s.get("label", "")))
        for j, it in enumerate(s.get("items", [])):
            out.append((f"skills[{i}].items[{j}]", it))
    out.append(("languages", cv.get("languages", "")))
    return [(f, t) for f, t in out if t]


# ---------- layer 1: schema ----------

def check_schema(cv):
    v = []
    for key in REQUIRED:
        if key not in cv:
            v.append(f"SCHEMA  missing required section: {key}")
        elif cv[key] in ("", [], {}, None):
            v.append(f"SCHEMA  section is empty: {key}")
    c = cv.get("contact", {})
    for key in ("name", "email", "phone", "links"):
        if not c.get(key):
            v.append(f"SCHEMA  contact.{key} missing or empty")
    for i, job in enumerate(cv.get("experience", [])):
        for key in ("role", "company", "dates", "bullets"):
            if not job.get(key):
                v.append(f"SCHEMA  experience[{i}].{key} missing or empty")
    for i, p in enumerate(cv.get("projects", [])):
        for key in ("title", "date", "description", "tech"):
            if not p.get(key):
                v.append(f"SCHEMA  projects[{i}].{key} missing or empty")
    return v


# ---------- layer 2: factual guard ----------

def _tech_vocab(text, canon):
    """Which canonical technology names appear in this text."""
    return {c for c in canon if re.search(LB + re.escape(c) + RB, text)}


def check_facts(cv, master):
    v = []
    # known_technologies is a denylist of things the master does NOT claim. Whose master
    # depends on who cloned this, so anything the master genuinely has is dropped from the
    # denylist first - otherwise a real skill reads as an invented one.
    master_blob = json.dumps(master)
    denied = [t for t in TERMS.get("known_technologies", [])
              if not re.search(LB + re.escape(t) + RB, master_blob)]
    canon = list(TERMS["canonical"]) + denied

    def norm(s):
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    pairs = [
        ("company",     [j["company"] for j in cv.get("experience", [])],
                        [j["company"] for j in master["experience"]]),
        ("date",        [j["dates"] for j in cv.get("experience", [])]
                        + [e["date"] for e in cv.get("education", [])]
                        + [c["date"] for c in cv.get("certificates", [])]
                        + [p["date"] for p in cv.get("projects", [])],
                        [j["dates"] for j in master["experience"]]
                        + [e["date"] for e in master["education"]]
                        + [c["date"] for c in master["certificates"]]
                        + [p["date"] for p in master["projects"]]),
        ("role",        [j["role"] for j in cv.get("experience", [])],
                        [j["role"] for j in master["experience"]]),
        ("degree",      [e["degree"] for e in cv.get("education", [])],
                        [e["degree"] for e in master["education"]]),
        ("institution", [e["institution"] for e in cv.get("education", [])],
                        [e["institution"] for e in master["education"]]),
        ("certificate", [c["name"] for c in cv.get("certificates", [])],
                        [c["name"] for c in master["certificates"]]),
        ("project",     [p["title"] for p in cv.get("projects", [])],
                        [p["title"] for p in master["projects"]]),
    ]
    for label, got, allowed in pairs:
        allowed_n = {norm(a) for a in allowed}
        for g in got:
            if norm(g) not in allowed_n:
                v.append(f"FACT    invented {label}: {g!r} is not in master-cv.json")

    # structural integrity: order and grouping are the user's, not the model's
    cv_titles = [x["title"] for x in cv.get("projects", [])]
    m_titles = [x["title"] for x in master["projects"]]
    if cv_titles != m_titles:
        v.append(f"ORDER   projects must stay in master order {m_titles}, got {cv_titles}")

    cv_labels = [g.get("label") for g in cv.get("skills", [])]
    m_labels = [g["label"] for g in master["skills"]]
    if cv_labels != m_labels:
        v.append(f"ORDER   skill groups must stay in master order {m_labels}, got {cv_labels}")

    m_items = {g["label"]: {norm(i) for i in g["items"]} for g in master["skills"]}
    for g in cv.get("skills", []):
        allowed = m_items.get(g.get("label"))
        if allowed is None:
            continue
        for it in g.get("items", []):
            if norm(it) not in allowed:
                v.append(f"FACT    invented skill: {it!r} is not in master group {g['label']!r}")

    cv_comp = [norm(x) for x in cv.get("experience", [])and
               [j["company"] for j in cv["experience"]]]
    if cv_comp != [norm(j["company"]) for j in master["experience"]]:
        v.append("ORDER   experience entries must stay in master order")

    master_tech = _tech_vocab(json.dumps(master), canon)
    for field, text in prose_of(cv):
        for t in _tech_vocab(text, canon) - master_tech:
            v.append(f"FACT    invented technology: {t!r} in {field} is not in master-cv.json")
    return v


# ---------- layer 3: terminology ----------

def _mask_canonicals(text, canon):
    """Blank out correct canonical names so variant checks can't match inside them."""
    for c in sorted(canon, key=len, reverse=True):
        text = re.sub(LB + re.escape(c) + RB, lambda m: "\x00" * len(m.group()), text)
    return text


def protected_phrases(master=None):
    """The generic protected list, plus every proper noun from the master. Whose institutions,
    employers and certificates those are depends on who cloned this, so they are read from the
    master rather than hardcoded - that keeps the committed config free of anyone's details."""
    phrases = list(TERMS["protected"])
    if not master:
        return phrases
    for e in master.get("education", []):
        phrases.append(e.get("institution", ""))
    for c in master.get("certificates", []):
        phrases += [c.get("name", ""), c.get("issuer", "")]
    for j in master.get("experience", []):
        phrases.append(j.get("company", ""))
    for p in master.get("projects", []):
        phrases.append(p.get("title", ""))
    # Longest first so a phrase that contains another is tested before its substring.
    return sorted({p for p in phrases if p}, key=len, reverse=True)


def check_terminology(cv, master=None):
    v = []
    canon = TERMS["canonical"]
    protected = protected_phrases(master)

    for field, text in prose_of(cv):
        # forbidden literals
        for bad in TERMS["forbidden"]:
            if bad in text:
                v.append(f"TERM    forbidden string {bad!r} in {field}")

        # protected phrases must survive verbatim and un-suffixed
        for p in protected:
            for m in re.finditer(re.escape(p), text):
                tail = text[m.start():]
                if len(tail) > len(p) and tail[len(p)].isalnum():
                    v.append(f"TERM    protected phrase corrupted: {tail[:len(p)+2]!r} in {field}")

        # non-canonical variants
        masked = _mask_canonicals(text, canon)
        for correct, variants in canon.items():
            for var in variants:
                if re.search(LB + re.escape(var) + RB, masked):
                    v.append(f"TERM    use {correct!r} not {var!r} in {field}")

        v += check_hyphenation(field, text)
    return v


def check_hyphenation(field, text):
    """front-end / back-end only when modifying a noun; front end / back end otherwise."""
    rules = TERMS["hyphenation"]
    nouns = set(rules["nouns_requiring_hyphen"])
    skip = {"and", "or", "a", "an", "the"} | {f"{c}-end" for c in rules["compounds"]} \
           | {f"{c}end" for c in rules["compounds"]}
    out = []
    for m in re.finditer(r"\b(front|back)([- ])end\b", text, re.I):
        word, sep = m.group(1).lower(), m.group(2)
        after = re.findall(r"[\w.-]+", text[m.end():m.end() + 60])[:3]
        needs_hyphen = False
        for tok in after:
            t = tok.lower().strip(".,;:")
            if t in skip:
                continue
            needs_hyphen = t in nouns
            break
        ctx = text[max(0, m.start() - 12):m.end() + 14].strip()
        if needs_hyphen and sep == " ":
            out.append(f"GRAMMAR hyphenate {word!r}-end (modifies a noun) in {field}: ...{ctx}...")
        elif not needs_hyphen and sep == "-":
            out.append(f"GRAMMAR {word} end should not be hyphenated (standalone noun) in {field}: ...{ctx}...")
    return out


# ---------- docx path (text-only subset of the checks) ----------

def validate_docx(path):
    text = docx_text(path)
    fake = {"headline": "", "summary": text, "core_competencies": [], "experience": [],
            "education": [], "certificates": [], "projects": [], "skills": [], "languages": ""}
    v = check_terminology(fake)
    return [x.replace(" in summary", "") for x in v]


# ---------- entry ----------

def validate(cv, master):
    return check_schema(cv) + check_facts(cv, master) + check_terminology(cv, master)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    target = Path(args[0])
    master_path = paths.MASTER
    if "--master" in sys.argv:
        master_path = Path(sys.argv[sys.argv.index("--master") + 1])

    if target.suffix == ".docx":
        violations = validate_docx(target)
    else:
        violations = validate(json.loads(target.read_text()),
                              json.loads(master_path.read_text()))

    if violations:
        print(f"FAIL  {len(violations)} violation(s) in {target.name}\n")
        for x in violations:
            print(" ", x)
        sys.exit(1)
    print(f"PASS  {target.name}")


if __name__ == "__main__":
    main()
