"""Jupyter notebook support.

Code cells are rewritten with the same import rewriter as ``.py`` files. IPython
magics (``%pip``, ``!ls``, ``df?``) are not Python, so they are replaced with a
comment marker while LibCST parses the cell and put back afterwards. Cells that
start with ``%%`` (cell magics) are not Python at all and are skipped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import libcst as cst

from langchain_v1_migrate.findings import Finding
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.rewrite import Needs, rewrite_source
from langchain_v1_migrate.table.load import MoveTable

_MARK = "#__lcm_magic_{}__"
_MARK_RE = re.compile(r"^(?P<indent>[ \t]*)#__lcm_magic_(?P<i>\d+)__(?P<nl>\r?\n?)$")
_HELP_RE = re.compile(r"^\s*(\?{1,2}[\w.]+|[\w.]+\?{1,2})\s*$")
_PIP_RE = re.compile(r"^(?P<indent>\s*)(?P<magic>[%!])\s*pip\s+install\b(?P<rest>.*)$")


@dataclass
class NotebookResult:
    text: str
    findings: list[Finding]
    needs: Needs
    #: per-notebook needs are also needed by the dependency step (pip lines)
    pip_needs: Needs = field(default_factory=Needs)


def _source_of(cell: dict[str, Any]) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def _set_source(cell: dict[str, Any], text: str) -> None:
    if isinstance(cell.get("source"), list):
        cell["source"] = text.splitlines(keepends=True)
    else:
        cell["source"] = text


def _is_magic(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("%", "!")) or bool(_HELP_RE.match(line))


def mask_magics(code: str) -> tuple[str, dict[int, str]]:
    """Replace magic lines (and their ``\\`` continuations) by comment markers."""
    saved: dict[int, str] = {}
    out: list[str] = []
    continuing = False
    for line in code.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        nl = line[len(body):]
        if continuing or _is_magic(body):
            indent = body[: len(body) - len(body.lstrip())]
            saved[len(saved)] = body
            out.append(f"{indent}{_MARK.format(len(saved) - 1)}{nl}")
            continuing = body.rstrip().endswith("\\")
        else:
            out.append(line)
    return "".join(out), saved


def unmask_magics(code: str, saved: dict[int, str]) -> str:
    out = []
    for line in code.splitlines(keepends=True):
        m = _MARK_RE.match(line)
        if m and int(m.group("i")) in saved:
            out.append(saved[int(m.group("i"))] + m.group("nl"))
        else:
            out.append(line)
    return "".join(out)


def _parses(code: str) -> bool:
    try:
        cst.parse_module(code)
        return True
    except cst.ParserSyntaxError:
        return False


def _detect_format(text: str) -> tuple[int, bool, bool]:
    """(indent, ensure_ascii, trailing newline) of an existing notebook file."""
    indent = 1
    m = re.search(r'\n( +)"', text)
    if m:
        indent = len(m.group(1))
    ensure_ascii = not any(ord(c) > 127 for c in text) and "\\u" in text
    return indent, ensure_ascii, text.endswith("\n")


def process_notebook(text: str, path: str, table: MoveTable, target: str) -> NotebookResult:
    """Return the (possibly) rewritten notebook text and the findings."""
    try:
        nb = json.loads(text)
        cells = nb["cells"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return NotebookResult(text, [Finding("LCM011", path, 1, 1, t("msg.LCM011", detail=f"not a notebook: {exc}"))], Needs())

    findings: list[Finding] = []
    needs = Needs()
    changed = False
    for number, cell in enumerate(cells, start=1):
        if cell.get("cell_type") != "code":
            continue
        code = _source_of(cell)
        if code.lstrip().startswith("%%"):
            findings.append(Finding("LCM010", path, 1, 1, t("msg.LCM010"), cell=number))
            continue
        saved: dict[int, str] = {}
        work = code
        if not _parses(code):
            work, saved = mask_magics(code)
        result = rewrite_source(work, path, table, target, cell=number)
        findings.extend(result.findings)
        needs.merge(result.needs)
        if result.source != work:
            new_code = unmask_magics(result.source, saved) if saved else result.source
            if new_code != code:
                _set_source(cell, new_code)
                changed = True
    if not changed:
        return NotebookResult(text, findings, needs, needs)
    indent, ensure_ascii, newline = _detect_format(text)
    out = json.dumps(nb, indent=indent, ensure_ascii=ensure_ascii)
    return NotebookResult(out + ("\n" if newline else ""), findings, needs, needs)


# --------------------------------------------------------------------------- #
# pip lines
# --------------------------------------------------------------------------- #

_SKIP_CHARS = ("&&", ";", "|", "#", "`", "$(")


def _pip_tokens(rest: str) -> list[str]:
    return [tok.strip("\"'") for tok in rest.split()]


def _req_name(token: str) -> str:
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", token)
    return re.sub(r"[-_.]+", "-", m.group(0)).lower() if m else ""


def update_pip_lines(text: str, path: str, needs: Needs) -> tuple[str, list[Finding]]:
    """Add the packages ``needs`` asks for to one ``%pip install`` line of a notebook.

    Returns the new notebook text and ``LCM013`` findings: fixable ones for the
    line that was (or would be) edited, non-fixable ones when no safe line exists.
    """
    if not needs.classic and not needs.community_direct and not needs.sqlalchemy and not needs.text_splitters:
        return text, []
    try:
        nb = json.loads(text)
        cells = nb["cells"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return text, []

    wanted: list[str] = []
    if needs.classic:
        wanted.append("langchain-classic")
    if needs.community_extra or needs.community_direct:
        wanted.append("langchain-community")
    if needs.text_splitters:
        wanted.append("langchain-text-splitters")
    if needs.sqlalchemy:
        wanted.append("sqlalchemy[asyncio]")

    pip_lines: list[tuple[int, int, str, re.Match[str]]] = []  # cell index, line index, text, match
    present: set[str] = set()
    for ci, cell in enumerate(cells):
        if cell.get("cell_type") != "code":
            continue
        lines = _source_of(cell).splitlines()
        for li, line in enumerate(lines):
            m = _PIP_RE.match(line)
            if m:
                pip_lines.append((ci, li, line, m))
                present.update(_req_name(tok) for tok in _pip_tokens(m.group("rest")))
    if not pip_lines:
        return text, []

    missing = [w for w in wanted if _req_name(w) not in present]
    if not missing:
        return text, []

    # prefer the first pip line that already installs langchain
    chosen = next(
        (p for p in pip_lines if "langchain" in {_req_name(tok) for tok in _pip_tokens(p[3].group("rest"))}),
        pip_lines[0],
    )
    ci, li, line, _m = chosen
    number = ci + 1
    if line.rstrip().endswith("\\") or any(ch in line for ch in _SKIP_CHARS):
        return text, [Finding("LCM013", path, li + 1, 1, t("msg.LCM013.pipmanual", packages=" ".join(missing)), cell=number, fixable=False)]

    new_line = line.rstrip() + " " + " ".join(missing)
    cell = cells[ci]
    src = _source_of(cell)
    parts = src.splitlines(keepends=True)
    old_part = parts[li]
    nl = old_part[len(old_part.rstrip("\r\n")):]
    parts[li] = new_line + nl
    _set_source(cell, "".join(parts))
    indent, ensure_ascii, newline = _detect_format(text)
    out = json.dumps(nb, indent=indent, ensure_ascii=ensure_ascii) + ("\n" if newline else "")
    finding = Finding("LCM013", path, li + 1, 1, t("msg.LCM013.pip", packages=" ".join(missing)), old=line.strip(), new=new_line.strip(), cell=number)
    return out, [finding]
