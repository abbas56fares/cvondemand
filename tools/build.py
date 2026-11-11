"""Orchestrator:  master-cv.json + job description -> validated cv.json -> .docx

    build.py "Full-Stack Developer (React.js, Node.js)" --jd path/to/jd.md

With --jd the model is called. Without it, an existing positions/<name>/cv.json is
re-validated and re-rendered (useful after a master or style change).
No .docx is written unless validation passes.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths
import render_cv
import tailor as tailor_mod
import validate as validate_mod

ROOT = paths.ROOT
MASTER = paths.MASTER


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("position")
    ap.add_argument("--jd", help="path to the job description; omit to re-render existing cv.json")
    ap.add_argument("--retries", type=int, default=1, help="re-prompts on validation failure")
    args = ap.parse_args()

    master = json.loads(MASTER.read_text())
    folder = ROOT / "positions" / args.position
    cv_path = folder / "cv.json"

    if args.jd:
        jd_src = Path(args.jd)
        jd = jd_src.read_text()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "job-descriptions").mkdir(exist_ok=True)
        (folder / "job-descriptions" / jd_src.name).write_text(jd)

        feedback, cv, used = "", None, None
        for attempt in range(args.retries + 1):
            used, cv = tailor_mod.tailor(master, jd, args.position, feedback)
            violations = validate_mod.validate(cv, master)
            if not violations:
                break
            print(f"attempt {attempt + 1} via {used}: {len(violations)} violation(s)")
            for v in violations:
                print("  ", v)
            feedback = "\n".join(violations)
        else:
            sys.exit("\nSTOPPED: validation still failing. No .docx written.")
        print(f"tailored via {used}")
        cv_path.write_text(json.dumps(cv, indent=2, ensure_ascii=False) + "\n")
    else:
        if not cv_path.exists():
            sys.exit(f"no cv.json at {cv_path} - pass --jd to create one")
        cv = json.loads(cv_path.read_text())
        violations = validate_mod.validate(cv, master)
        if violations:
            print(f"FAIL  {len(violations)} violation(s) in {cv_path}\n")
            for v in violations:
                print("  ", v)
            sys.exit("\nNo .docx written.")

    out = folder / render_cv.output_name(cv, args.position)
    render_cv.build(cv, out)
    print(f"PASS  validated\nwrote {out}")


if __name__ == "__main__":
    main()
