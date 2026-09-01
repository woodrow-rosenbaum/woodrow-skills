#!/usr/bin/env python3
"""
Keep marketplace.json and plugin.json descriptions in sync with each plugin's
SKILL.md frontmatter, so the discovery surface never drifts from the skill.

    python scripts/sync_descriptions.py           # check only, exits 1 on drift
    python scripts/sync_descriptions.py --write   # fix in place

Wire the check into CI to stop drift landing on main.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def frontmatter_description(skill_md: Path) -> str | None:
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    d = re.search(r'^description:\s*"(.*)"\s*$', m.group(1), re.M)
    return d.group(1) if d else None


def first_skill_description(plugin_dir: Path) -> str | None:
    skills = sorted((plugin_dir / "skills").glob("*/SKILL.md"))
    for s in skills:
        desc = frontmatter_description(s)
        if desc:
            return desc
    return None


def main() -> int:
    write = "--write" in sys.argv
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    drift = []

    for entry in data.get("plugins", []):
        plugin_dir = (ROOT / entry["source"]).resolve()
        desc = first_skill_description(plugin_dir)
        if not desc:
            print(f"warn: no SKILL.md description under {plugin_dir}")
            continue

        if entry.get("description") != desc:
            drift.append(entry["name"])
            entry["description"] = desc

        pj_path = plugin_dir / ".claude-plugin" / "plugin.json"
        if pj_path.exists():
            pj = json.loads(pj_path.read_text(encoding="utf-8"))
            if pj.get("description") != desc:
                drift.append(f"{entry['name']}/plugin.json")
                pj["description"] = desc
                if write:
                    pj_path.write_text(
                        json.dumps(pj, indent=2) + "\n", encoding="utf-8"
                    )

    if not drift:
        print("descriptions in sync")
        return 0

    if write:
        MARKETPLACE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("updated:", ", ".join(drift))
        return 0

    print("drift detected:", ", ".join(drift))
    print("run with --write to fix")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
