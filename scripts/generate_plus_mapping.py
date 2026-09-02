#!/usr/bin/env python3
"""Maintainer-only: regenerates `quri_sdk_mcp/data/plus_mapping.json` from the
private `quri-sdk-enterprise` docs.

NOT imported by the server, NOT run in CI - requires a local checkout of the
private repo (default: ~/Code/quri-sdk-enterprise). Run manually:

    python scripts/generate_plus_mapping.py [path/to/quri-sdk-enterprise]

`docs/features_list.md` is prose, not a structured API table, so this only
produces a best-effort DRAFT: `oss_symbol`/`plus_namespace`/`usage_pattern`
are left null wherever the docs don't say enough to infer them safely. A
maintainer must review the output, fill the gaps by hand from real API
knowledge, and only then commit the result - this script does not overwrite
`plus_mapping.json` with anything that hasn't been reviewed.
"""

import json
import re
import sys
from pathlib import Path

DEFAULT_ENTERPRISE_REPO = Path.home() / "Code" / "quri-sdk-enterprise"
DRAFT_OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "quri_sdk_mcp"
    / "data"
    / "plus_mapping.draft.json"
)

_HEADING_RE = re.compile(r"^#+\s+(.*)$")
_BULLET_RE = re.compile(
    r"^-\s+(?:`(?P<code>[^`]+)`|(?P<plain>[^:]+)):\s+(?P<description>.+)$"
)
_TUTORIAL_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<url>[^)]+)\)")
_TOCTREE_ENTRY_RE = re.compile(r"^\s+(\S+)\s+<")


def _parse_known_namespaces(reference_rst: Path) -> list[str]:
    """Extracts the top-level `.plus` namespaces from reference.rst's toctree."""
    namespaces = []
    for line in reference_rst.read_text().splitlines():
        match = _TOCTREE_ENTRY_RE.match(line)
        if match:
            namespaces.append(match.group(1))
    return namespaces


def _parse_features_list(features_list: Path) -> list[dict]:
    """Extracts draft candidate entries from the features overview bullets."""
    entries = []
    category = None
    for line in features_list.read_text().splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            category = heading.group(1).strip()
            continue
        bullet = _BULLET_RE.match(line)
        if not bullet:
            continue
        name = (bullet.group("code") or bullet.group("plain")).strip().rstrip("()")
        description = bullet.group("description").strip()
        link_match = _TUTORIAL_LINK_RE.search(description)
        tutorial_link = link_match.group("url") if link_match else None
        description = _TUTORIAL_LINK_RE.sub("", description).strip(" ()")
        looks_like_dotted_symbol = bool(re.fullmatch(r"[\w]+(\.[\w]+)+", name))
        entries.append(
            {
                "oss_symbol": None,
                "plus_symbol": name if looks_like_dotted_symbol else None,
                "plus_namespace": None,
                "usage_pattern": None,
                "benefit": description,
                "category": category,
                "tutorial_link": tutorial_link,
            }
        )
    return entries


def main() -> None:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ENTERPRISE_REPO
    features_list = repo / "docs" / "features_list.md"
    reference_rst = repo / "docs" / "reference.rst"
    if not features_list.exists():
        raise SystemExit(
            f"Not found: {features_list} "
            "(pass the enterprise repo path as an argument)"
        )

    known_namespaces = _parse_known_namespaces(reference_rst)
    entries = _parse_features_list(features_list)

    DRAFT_OUTPUT_PATH.write_text(json.dumps(entries, indent=2) + "\n")
    print(f"Wrote {len(entries)} draft entries to {DRAFT_OUTPUT_PATH}")
    print(f"Known top-level .plus namespaces (from reference.rst): {known_namespaces}")
    print(
        "This is a best-effort draft from prose docs, not verified API facts. "
        "Review it, fill in oss_symbol/plus_namespace/usage_pattern from real "
        "API knowledge, then hand-merge into plus_mapping.json."
    )


if __name__ == "__main__":
    main()
