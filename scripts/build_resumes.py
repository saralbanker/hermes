#!/usr/bin/env python3
"""
build_resumes.py — Render profile/resume.yaml into three ATS-friendly PDFs.

Single column, real text (no icons, tables or images), standard section
names, links as plain text so every ATS extracts them. Printed with headless
Chrome (already installed) — no LaTeX/LibreOffice dependency.

    python scripts/build_resumes.py            # → resumes/resume-{fullstack,backend,ai}.pdf
"""
from __future__ import annotations

import html
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
SOURCE = ROOT / "profile" / "resume.yaml"
OUT_DIR = ROOT / "resumes"
CHROME = "google-chrome-stable"

CSS = """
@page { size: A4; margin: 10mm 13mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 9.6pt; line-height: 1.3; color: #111; margin: 0; }
h1 { font-size: 20pt; margin: 0; letter-spacing: .5px; }
.headline { font-size: 11pt; font-weight: bold; color: #333; margin: 2px 0 4px; }
.contact { font-size: 9.5pt; color: #222; }
.contact a { color: #1a4fa0; text-decoration: none; }
h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #999;
     margin: 9px 0 4px; padding-bottom: 2px; }
.row { display: flex; justify-content: space-between; font-weight: bold; }
.sub { font-style: italic; color: #333; }
ul { margin: 2px 0 5px 16px; padding: 0; }
li { margin: 1.5px 0; }
.skills div { margin: 1.5px 0; }
p { margin: 3px 0; }
"""


def esc(text: str) -> str:
    return html.escape(str(text))


def section_experience(data: dict) -> str:
    parts = ["<h2>Experience</h2>"]
    for job in data["experience"]:
        bullets = "".join(f"<li>{esc(b)}</li>" for b in job["bullets"])
        parts.append(f'<div class="row"><span>{esc(job["role"])}</span><span>{esc(job["dates"])}</span></div>'
                     f'<div class="sub">{esc(job["where"])}</div><ul>{bullets}</ul>')
    return "".join(parts)


def section_projects(data: dict, order: list[str]) -> str:
    parts = ["<h2>Projects</h2>"]
    for key in order:
        p = data["projects"][key]
        link = f' · {esc(p["link"])}' if p.get("link") else ""
        bullets = "".join(f"<li>{esc(b)}</li>" for b in p["bullets"])
        parts.append(f'<div class="row"><span>{esc(p["name"])}</span><span>{esc(p["dates"])}</span></div>'
                     f'<div class="sub">{esc(p["stack"])}{link}</div><ul>{bullets}</ul>')
    return "".join(parts)


def section_skills(data: dict, order: list[str]) -> str:
    rows = "".join(f"<div><b>{esc(data['skills'][k][0])}:</b> {esc(data['skills'][k][1])}</div>" for k in order)
    return f'<h2>Technical Skills</h2><div class="skills">{rows}</div>'


def render(data: dict, variant: str) -> str:
    v, c, e = data["variants"][variant], data["contact"], data["education"]
    links = " · ".join(f'<a href="{esc(url)}">{esc(label)}</a>' for label, url in c["links"])
    education = (f'<h2>Education</h2><div class="row"><span>{esc(e["degree"])} — {esc(e["school"])}</span>'
                 f'<span>{esc(e["dates"])}</span></div><p>{esc(e["detail"])}</p>')
    body = (f"<h1>{esc(c['name'])}</h1><div class='headline'>{esc(v['headline'])}</div>"
            f"<div class='contact'>{esc(c['line'])}<br>{links}</div>"
            f"<h2>Summary</h2><p>{esc(v['summary'])}</p>"
            f"{section_skills(data, v['skills_order'])}{section_experience(data)}"
            f"{section_projects(data, v['project_order'])}{education}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Saral Banker Resume</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def print_pdf(html_text: str, out: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as tmp:
        tmp.write(html_text)
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={out}", f"file://{tmp.name}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    Path(tmp.name).unlink(missing_ok=True)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"Chrome PDF render failed for {out.name}: {result.stderr[-400:]}")


def main() -> int:
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(exist_ok=True)
    for variant in data["variants"]:
        out = OUT_DIR / f"resume-{variant}.pdf"
        print_pdf(render(data, variant), out)
        print(f"[resume] wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
