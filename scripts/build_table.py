"""Rebuild the bundled move table (maintainers; needs network and uv).

    uv run python scripts/build_table.py [--computed-on YYYY-MM-DD]

Creates two temporary virtual environments, installs the pinned releases below,
reads their package trees with ``langchain_v1_migrate.table.compute`` (nothing
is imported) and writes ``src/langchain_v1_migrate/table/data/move_table.json.gz``.
To move to newer releases, change the pins and re-run; the tests that check the
counts (AC-1) then show what changed.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import tempfile
from pathlib import Path

OLD_PINS = ["langchain==0.3.29"]
NEW_PINS = ["langchain==1.5.0", "langchain-classic==1.0.8"]
COMMUNITY_PINS = ["langchain-community==0.4.2"]
PYTHON = "3.12"

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "src" / "langchain_v1_migrate" / "table" / "data" / "move_table.json.gz"


def make_env(base: Path, name: str, pins: list[str]) -> Path:
    venv = base / name
    subprocess.run(["uv", "venv", "--python", PYTHON, str(venv)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *pins], check=True)
    sites = sorted((venv / "lib").glob("python*/site-packages"))
    if not sites:
        raise SystemExit(f"no site-packages found in {venv}")
    return sites[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--computed-on", default=datetime.date.today().isoformat())
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from langchain_v1_migrate.table import compute

    with tempfile.TemporaryDirectory(prefix="lcm-table-") as tmp:
        base = Path(tmp)
        old_site = make_env(base, "old", OLD_PINS)
        new_site = make_env(base, "new", NEW_PINS)
        community_site = make_env(base, "community", COMMUNITY_PINS)
        table = compute.build_table(old_site, new_site, args.computed_on, community_site)
        compute.write_table(table, OUTPUT)
        print(f"wrote {OUTPUT}")
        print(table["meta"], table["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
