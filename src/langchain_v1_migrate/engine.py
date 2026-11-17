"""Run the migration over files and collect findings and pending changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_v1_migrate import deps, notebook
from langchain_v1_migrate.findings import Finding
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.rewrite import Needs, rewrite_source
from langchain_v1_migrate.table.load import MoveTable
from langchain_v1_migrate.walk import Targets


@dataclass
class RunResult:
    findings: list[Finding] = field(default_factory=list)
    #: path -> (old text, new text) for every file that would change
    changes: dict[Path, tuple[str, str]] = field(default_factory=dict)
    files: int = 0
    needs: Needs = field(default_factory=Needs)


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def run(targets: Targets, table: MoveTable, target: str = "classic", with_deps: bool = True) -> RunResult:
    """Analyse (and compute rewrites for) everything in ``targets``. Writes nothing."""
    result = RunResult()
    notebook_texts: dict[Path, tuple[str, str, Needs]] = {}

    for path in targets.python:
        result.files += 1
        text = _read(path)
        if text is None:
            result.findings.append(Finding("LCM011", str(path), 1, 1, t("msg.LCM011", detail="not readable as UTF-8")))
            continue
        res = rewrite_source(text, str(path), table, target)
        result.findings.extend(res.findings)
        result.needs.merge(res.needs)
        if res.source != text:
            result.changes[path] = (text, res.source)

    for path in targets.notebooks:
        result.files += 1
        text = _read(path)
        if text is None:
            result.findings.append(Finding("LCM011", str(path), 1, 1, t("msg.LCM011", detail="not readable as UTF-8")))
            continue
        nb = notebook.process_notebook(text, str(path), table, target)
        result.findings.extend(nb.findings)
        result.needs.merge(nb.needs)
        notebook_texts[path] = (text, nb.text, nb.needs)

    if with_deps:
        for path in targets.requirements:
            result.files += 1
            text = _read(path)
            if text is None:
                continue
            new, found = deps.update_requirements(text, str(path), result.needs)
            result.findings.extend(found)
            if new != text:
                result.changes[path] = (text, new)
        for path in targets.pyprojects:
            text = _read(path)
            if text is None:
                continue
            new, found = deps.update_pyproject(text, str(path), result.needs)
            if found:
                result.files += 1
            result.findings.extend(found)
            if new != text:
                result.changes[path] = (text, new)

    for path, (old, new, needs) in notebook_texts.items():
        if with_deps:
            new, found = notebook.update_pip_lines(new, str(path), needs)
            result.findings.extend(found)
        if new != old:
            result.changes[path] = (old, new)

    result.findings.sort(key=lambda f: (f.path, f.cell, f.line, f.col, f.code))
    return result
