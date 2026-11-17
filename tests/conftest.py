from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from langchain_v1_migrate import engine, i18n
from langchain_v1_migrate.table import load
from langchain_v1_migrate.walk import collect

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def english(monkeypatch):
    """Every test starts in English with no language variables leaking in."""
    for var in ("LANGCHAIN_V1_MIGRATE_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    i18n.set_lang("en")
    yield
    i18n.set_lang("en")


@pytest.fixture(scope="session")
def table():
    return load.bundled()


def migrate_tree(src: Path, dest: Path, table, target: str = "classic", with_deps: bool = True) -> engine.RunResult:
    """Copy ``src`` to ``dest`` and apply every change there."""
    shutil.copytree(src, dest)
    result = engine.run(collect([str(dest)]), table, target, with_deps=with_deps)
    for path, (_old, new) in result.changes.items():
        path.write_bytes(new.encode("utf-8"))
    return result


def read_tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
