#!/usr/bin/env python3
"""Check the skill against AUTHORING.md: front matter, sizes, links, and nothing sensitive.

    python3 scripts/validate.py            # exit 1 on any error
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Generic checks for anything that must not be published. Environment-specific strings (a lab's
# hostnames, logins, names) go in .validate-local, one regex per line: that file is gitignored.
SENSITIVE = [
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "IP address"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]*[a-z]{2,}", "email address"),
    (r"-----BEGIN [A-Z ]*(PRIVATE KEY|CERTIFICATE)-----", "key or certificate"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JWT"),
    (r"\b(?=[A-Z0-9]*[0-9])(?=[A-Z0-9]*[A-Z])[A-Z0-9]{20}\b", "access-key-like string"),
    (r"(?<![A-Za-z0-9/+_.-])(?=[A-Za-z0-9+/]*[0-9])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*[A-Z])[A-Za-z0-9+/]{40}(?![A-Za-z0-9/+_.-])", "secret-like string"),
    (r"/U[s]ers/[A-Za-z]|/h[o]me/[a-z]", "local path"),
]
ALLOWED = {"2.0.14.1"}          # version numbers that look like IP addresses
LOCAL = ROOT / ".validate-local"
if LOCAL.exists():
    SENSITIVE += [(line.strip(), "local pattern") for line in LOCAL.read_text().splitlines()
                  if line.strip() and not line.startswith("#")]
errors, warnings = [], []


def front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"')
    return fm


for skill in sorted((ROOT / "skills").iterdir()):
    if not skill.is_dir():
        continue
    md = skill / "SKILL.md"
    if not md.exists():
        errors.append(f"{skill.name}: no SKILL.md")
        continue
    text = md.read_text()
    fm = front_matter(text)
    if fm is None:
        errors.append(f"{skill.name}: no YAML front matter")
        continue
    if set(fm) - {"name", "description"}:
        warnings.append(f"{skill.name}: extra front matter keys {sorted(set(fm) - {'name', 'description'})}")
    if fm.get("name") != skill.name:
        errors.append(f"{skill.name}: name {fm.get('name')!r} != folder name")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm.get("name", "")) or len(fm.get("name", "")) > 64:
        errors.append(f"{skill.name}: bad name")
    d = fm.get("description", "")
    if not d or len(d) > 1024:
        errors.append(f"{skill.name}: description length {len(d)} (1-1024)")
    body_lines = len(text.splitlines())
    if body_lines > 500:
        warnings.append(f"{skill.name}: SKILL.md is {body_lines} lines (aim for < 400)")
    if "Verified" not in text:
        warnings.append(f"{skill.name}: no Verified line")
    for f in skill.rglob("*.md"):
        for m in re.finditer(r"\]\(((?!https?://|#|mailto:)[^)\s]+)\)", f.read_text()):
            target = (f.parent / m.group(1).split("#")[0]).resolve()
            if not target.exists():
                errors.append(f"{f.relative_to(ROOT)}: broken link {m.group(1)}")

for f in ROOT.rglob("*"):
    if f.is_file() and ".git" not in f.parts and f.name not in ("LICENSE", ".validate-local") \
            and f.suffix in (".md", ".py", ".sh", ".json", ".txt", ".yaml", ".yml", ""):
        t = f.read_text(errors="replace")
        for pat, what in SENSITIVE:
            for m in re.finditer(pat, t):
                if m.group(0) in ALLOWED:
                    continue
                line = t[:m.start()].count("\n") + 1
                errors.append(f"{f.relative_to(ROOT)}:{line}: {what} {m.group(0)!r}")

for w in warnings:
    print("warning:", w)
for e in errors:
    print("error:", e)
print(f"{len(errors)} errors, {len(warnings)} warnings")
sys.exit(1 if errors else 0)
