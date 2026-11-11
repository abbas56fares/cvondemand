"""cv.json -> .docx in the locked CV format.

Section order is hardcoded here on purpose: no model and no data file can reorder it.
Geometry comes from config/style.json.
"""
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
STYLE = json.loads((ROOT / "config" / "style.json").read_text())

F = STYLE["font"]
SP = STYLE["spacing"]


# ---------- low-level helpers ----------

def _run(p, text, *, bold=False, size=None, color=None):
    r = p.add_run(text)
    r.bold = bold
    r.font.name = F["family"]
    r.font.size = Pt(size or F["body_pt"])
    # East-Asian font name must be set separately or Word substitutes
    r._element.rPr.rFonts.set(qn("w:eastAsia"), F["family"])
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return r


def add_hyperlink(p, text, url):
    """python-docx has no hyperlink API: create the relationship and w:hyperlink by hand."""
    r_id = p.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    for tag, attrs in (
        ("w:rFonts", {"w:ascii": F["family"], "w:hAnsi": F["family"], "w:cs": F["family"]}),
        ("w:color", {"w:val": STYLE["link_color"]}),
        ("w:u", {"w:val": "single"}),
        ("w:sz", {"w:val": str(F["body_pt"] * 2)}),
    ):
        el = OxmlElement(tag)
        for k, v in attrs.items():
            el.set(qn(k), v)
        rPr.append(el)
    run.append(rPr)

    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    p._p.append(link)
    return link


def _bottom_border(p):
    p._p.get_or_add_pPr().append(
        parse_xml(f'<w:pBdr {nsdecls("w")}>'
                  f'<w:bottom w:val="single" w:sz="6" w:space="2" w:color="000000"/></w:pBdr>')
    )


# ---------- paragraph builders ----------

def centered(doc, after=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(SP["header_after_pt"] if after is None else after)
    return p


def section(doc, title):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(SP["heading_before_pt"])
    p.paragraph_format.space_after = Pt(SP["heading_after_pt"])
    p.paragraph_format.keep_with_next = True
    _run(p, title, bold=True, size=F["heading_pt"])
    _bottom_border(p)
    return p


def body(doc, runs):
    """runs: list of (text, bold) tuples."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(SP["body_after_pt"])
    for text, bold in runs:
        _run(p, text, bold=bold)
    return p


def titled(doc, left, right):
    """Bold title on the left, bold date flush right via a right tab stop."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(SP["titled_before_pt"])
    p.paragraph_format.space_after = Pt(SP["titled_after_pt"])
    p.paragraph_format.keep_with_next = True
    # WD_TAB_ALIGNMENT, not WD_ALIGN_PARAGRAPH - the latter silently produces a left tab
    p.paragraph_format.tab_stops.add_tab_stop(
        Inches(STYLE["tab_stop_in"]), WD_TAB_ALIGNMENT.RIGHT
    )
    _run(p, left, bold=True)
    _run(p, "\t" + right, bold=True)
    return p


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(SP["bullet_after_pt"])
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.first_line_indent = Inches(-0.14)
    _run(p, text)
    return p


# ---------- naming ----------

def output_name(cv, position):
    """'<Name> - <Position>.docx', from the CV's own contact block rather than a hardcoded
    name. Path separators and a leading dot are stripped so a typed name cannot escape the
    position folder or create a hidden file."""
    who = re.sub(r"[/\\]", "-", (cv.get("contact", {}).get("name") or "CV")).strip(". ")
    return f"{who or 'CV'} - {position}.docx"


# ---------- document ----------

def build(cv, out_path):
    doc = Document()

    for s in doc.sections:
        s.page_width = Inches(STYLE["page"]["width_in"])
        s.page_height = Inches(STYLE["page"]["height_in"])
        m = Inches(STYLE["page"]["margin_in"])
        s.top_margin = s.bottom_margin = s.left_margin = s.right_margin = m

    normal = doc.styles["Normal"].font
    normal.name = F["family"]
    normal.size = Pt(F["body_pt"])

    c = cv["contact"]

    # --- header ---
    p = centered(doc)
    _run(p, c["name"], bold=True, size=F["name_pt"])

    p = centered(doc)
    _run(p, "Nationality: ", bold=True)
    _run(p, f'{c["nationality"]} | ')
    _run(p, "Address: ", bold=True)
    _run(p, c["address"])

    p = centered(doc)
    _run(p, "Email: ", bold=True)
    add_hyperlink(p, c["email"], f'mailto:{c["email"]}')
    _run(p, " | ")
    _run(p, "Phone Number: ", bold=True)
    add_hyperlink(p, c["phone"], "tel:" + c["phone"].replace(" ", ""))

    p = centered(doc)
    for i, link in enumerate(c["links"]):
        if i:
            _run(p, " | ")
        add_hyperlink(p, link["label"], link["url"])

    p = centered(doc, after=0)
    p.paragraph_format.space_before = Pt(5)
    _run(p, cv["headline"], bold=True)

    # --- 1. SUMMARY ---
    section(doc, "SUMMARY")
    body(doc, [(cv["summary"], False)])

    # --- 2. CORE COMPETENCIES ---
    section(doc, "CORE COMPETENCIES")
    body(doc, [(", ".join(cv["core_competencies"]) + ".", False)])

    # --- 3. PROFESSIONAL EXPERIENCE ---
    section(doc, "PROFESSIONAL EXPERIENCE")
    for job in cv["experience"]:
        titled(doc, f'{job["role"]} | {job["company"]}', job["dates"])
        for b in job["bullets"]:
            bullet(doc, b)

    # --- 4. EDUCATION ---
    section(doc, "EDUCATION")
    for e in cv["education"]:
        titled(doc, f'{e["degree"]} | {e["institution"]}', e["date"])

    # --- 5. TRAINING AND CERTIFICATES ---
    section(doc, "TRAINING AND CERTIFICATES")
    for cert in cv["certificates"]:
        titled(doc, f'{cert["name"]} | {cert["issuer"]}', cert["date"])

    # --- 6. PROJECTS ---
    section(doc, "PROJECTS")
    for pr in cv["projects"]:
        titled(doc, pr["title"], pr["date"])
        body(doc, [(pr["description"], False)])
        body(doc, [("Technologies Used: ", True), (pr["tech"], False)])

    # --- 7. SKILLS ---
    section(doc, "SKILLS")
    for grp in cv["skills"]:
        body(doc, [(grp["label"] + ": ", True), (", ".join(grp["items"]) + ".", False)])

    # --- 8. LANGUAGES ---
    section(doc, "LANGUAGES")
    body(doc, [(cv["languages"], False)])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: render_cv.py <cv.json> <out.docx>")
    cv = json.loads(Path(sys.argv[1]).read_text())
    out = build(cv, sys.argv[2])
    print(f"rendered -> {out}")


if __name__ == "__main__":
    main()
