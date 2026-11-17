"""Text, JSON and diff output."""

from __future__ import annotations

import difflib
import json
import unicodedata
from pathlib import Path

from langchain_v1_migrate import __version__
from langchain_v1_migrate.findings import Finding, summarize
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.table.load import MoveTable


def table_label(table: MoveTable) -> str:
    frm = ", ".join(f"{k} {v}" for k, v in table.meta["from"].items())
    to = " + ".join(f"{k} {v}" for k, v in table.meta["to"].items())
    return f"{frm} -> {to}"


def render_json(findings: list[Finding], files: int, table: MoveTable, target: str) -> str:
    payload = {
        "schema": 1,
        "tool": {"name": "langchain-v1-migrate", "version": __version__},
        "target": target,
        "table": {"from": table.meta["from"], "to": table.meta["to"]},
        "findings": [f.as_dict() for f in findings],
        "summary": summarize(findings, files),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _width(text: str) -> int:
    """Display width: Hangul and other wide characters take two terminal columns."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _where(f: Finding) -> str:
    cell = f"cell{f.cell}:" if f.cell else ""
    return f"{cell}{f.line}:{f.col}"


def render_text(findings: list[Finding], files: int, table: MoveTable) -> str:
    lines = [t("report.header", version=__version__, table=table_label(table))]
    current = None
    for f in findings:
        if f.path != current:
            current = f.path
            lines.append("")
            lines.append(f.path)
        mark = t("report.fixable") if f.fixable else t(f"report.severity.{f.severity}")
        lines.append(f"  {_pad(_where(f), 10)} {f.code}  {_pad(mark, 9)} {f.message}")
    summary = summarize(findings, files)
    lines.append("")
    if not findings:
        lines.append(t("report.clean", files=files))
    lines.append(t("report.summary", **summary))
    return "\n".join(lines) + "\n"


def render_diff(changes: dict[Path, tuple[str, str]]) -> str:
    chunks = []
    for path in sorted(changes):
        old, new = changes[path]
        diff = difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        for line in diff:
            chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(chunks)
