"""Dependency files: add what the migrated code needs.

Handled: ``requirements*.txt`` and ``pyproject.toml`` (PEP 621
``[project].dependencies`` and ``[tool.poetry.dependencies]``). Notebook
``%pip`` lines live in :mod:`notebook`. Lock files, ``setup.py`` and friends are
never edited.
"""

from __future__ import annotations

import re

import tomlkit
from tomlkit.exceptions import TOMLKitError

from langchain_v1_migrate.findings import Finding
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.rewrite import Needs

CLASSIC_RANGE = ">=1.0,<2"
COMMUNITY_RANGE = ">=0.4"
TEXT_SPLITTERS_RANGE = ">=1.1,<2"
MIN_CLASSIC_PYTHON = (3, 10)

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?\s*(.*)$")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(text: str) -> tuple[str, frozenset[str], str] | None:
    """``"langchain-classic[community]>=1.0"`` -> (name, extras, specifier)."""
    body = text.split("#", 1)[0].split(";", 1)[0].strip()
    m = _NAME_RE.match(body)
    if not m:
        return None
    extras = frozenset(e.strip().lower() for e in (m.group(2) or "").split(",") if e.strip())
    return normalize(m.group(1)), extras, m.group(3).strip()


def _old_pin(spec: str) -> bool:
    """True if a ``langchain`` specifier keeps the project on 0.x."""
    return bool(re.search(r"(==|~=|<=?)\s*0\.|<\s*1(\.0)*(\s|,|$)", spec))


class _Present:
    """What a dependency file already lists."""

    def __init__(self) -> None:
        self.extras: dict[str, frozenset[str]] = {}
        self.langchain_spec: str | None = None

    def add(self, name: str, extras: frozenset[str], spec: str) -> None:
        name = normalize(name)
        self.extras[name] = self.extras.get(name, frozenset()) | extras
        if name == "langchain":
            self.langchain_spec = spec

    def has(self, name: str) -> bool:
        return name in self.extras


def _plan(needs: Needs, present: _Present) -> list[tuple[str, str, str]]:
    """What to add: (distribution, PEP 508 string, poetry-style spec description)."""
    add: list[tuple[str, str, str]] = []
    classic_has_community = "community" in present.extras.get("langchain-classic", frozenset())
    if needs.classic and not present.has("langchain-classic"):
        if needs.community_extra:
            add.append(("langchain-classic", f"langchain-classic[community]{CLASSIC_RANGE}", "classic+community"))
            classic_has_community = True
        else:
            add.append(("langchain-classic", f"langchain-classic{CLASSIC_RANGE}", "classic"))
    want_community = needs.community_direct or needs.community_extra
    if want_community and not classic_has_community and not present.has("langchain-community"):
        add.append(("langchain-community", f"langchain-community{COMMUNITY_RANGE}", "community"))
    if needs.text_splitters and not present.has("langchain-text-splitters"):
        add.append(("langchain-text-splitters", f"langchain-text-splitters{TEXT_SPLITTERS_RANGE}", "text-splitters"))
    if needs.sqlalchemy and "asyncio" not in present.extras.get("sqlalchemy", frozenset()) and not present.has("greenlet"):
        add.append(("sqlalchemy", "sqlalchemy[asyncio]", "sqlalchemy"))
    return add


# --------------------------------------------------------------------------- #
# requirements.txt
# --------------------------------------------------------------------------- #


def update_requirements(text: str, path: str, needs: Needs) -> tuple[str, list[Finding]]:
    if not needs.any():
        return text, []
    present = _Present()
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        parsed = parse_requirement(stripped)
        if parsed:
            present.add(*parsed)
    findings: list[Finding] = []
    if present.langchain_spec is not None and _old_pin(present.langchain_spec):
        findings.append(Finding("LCM012", path, 1, 1, t("msg.LCM012.pin", spec=f"langchain{present.langchain_spec}")))
    add = _plan(needs, present)
    if not add:
        return text, findings
    if "--hash" in text:
        findings.append(Finding("LCM013", path, 1, 1, t("msg.LCM013.hash", packages=", ".join(a[1] for a in add)), fixable=False))
        return text, findings
    newline = "\r\n" if "\r\n" in text else "\n"
    out = text if (not text or text.endswith(("\n", "\r"))) else text + newline
    line_no = len(lines) + 1
    for _dist, spec, _kind in add:
        out += spec + newline
        findings.append(Finding("LCM013", path, line_no, 1, t("msg.LCM013.add", package=spec), new=spec))
        line_no += 1
    return out, findings


# --------------------------------------------------------------------------- #
# pyproject.toml
# --------------------------------------------------------------------------- #


def _requires_python_finding(doc, path: str) -> Finding | None:
    project = doc.get("project")
    spec = project.get("requires-python") if project is not None else None
    if not spec:
        return None
    m = re.search(r">=\s*(\d+)\.(\d+)", str(spec))
    if m and (int(m.group(1)), int(m.group(2))) < MIN_CLASSIC_PYTHON:
        return Finding("LCM012", path, 1, 1, t("msg.LCM012.python", spec=str(spec)))
    if not m:
        return Finding("LCM012", path, 1, 1, t("msg.LCM012.python", spec=str(spec)))
    return None


def update_pyproject(text: str, path: str, needs: Needs) -> tuple[str, list[Finding]]:
    if not needs.any():
        return text, []
    try:
        doc = tomlkit.parse(text)
    except TOMLKitError:
        return text, [Finding("LCM011", path, 1, 1, t("msg.LCM011", detail="invalid TOML"))]

    findings: list[Finding] = []
    changed = False
    project = doc.get("project")
    pep621 = project.get("dependencies") if project is not None else None
    tool = doc.get("tool")
    poetry = tool.get("poetry") if tool is not None else None
    poetry_deps = poetry.get("dependencies") if poetry is not None else None

    if pep621 is not None:
        present = _Present()
        for item in pep621:
            parsed = parse_requirement(str(item))
            if parsed:
                present.add(*parsed)
        if present.langchain_spec is not None and _old_pin(present.langchain_spec):
            findings.append(Finding("LCM012", path, 1, 1, t("msg.LCM012.pin", spec=f"langchain{present.langchain_spec}")))
        for _dist, spec, _kind in _plan(needs, present):
            pep621.append(spec)
            changed = True
            findings.append(Finding("LCM013", path, 1, 1, t("msg.LCM013.add", package=spec), new=spec))
        py = _requires_python_finding(doc, path)
        if py:
            findings.append(py)

    if poetry_deps is not None:
        present = _Present()
        for key, value in poetry_deps.items():
            if key.lower() == "python":
                continue
            spec = value if isinstance(value, str) else str(value.get("version", "")) if hasattr(value, "get") else ""
            extras = frozenset(str(e).lower() for e in value.get("extras", [])) if hasattr(value, "get") else frozenset()
            present.add(key, extras, spec)
        if present.langchain_spec is not None and _old_pin(present.langchain_spec):
            findings.append(Finding("LCM012", path, 1, 1, t("msg.LCM012.pin", spec=f"langchain {present.langchain_spec}")))
        for dist, spec, kind in _plan(needs, present):
            if kind == "classic+community":
                value = tomlkit.inline_table()
                value["version"] = CLASSIC_RANGE
                value["extras"] = ["community"]
            elif kind == "sqlalchemy":
                value = tomlkit.inline_table()
                value["version"] = "*"
                value["extras"] = ["asyncio"]
            else:
                value = spec[len(dist):]
            poetry_deps[dist] = value
            changed = True
            findings.append(Finding("LCM013", path, 1, 1, t("msg.LCM013.add", package=spec), new=spec))

    if not changed:
        return text, findings
    return tomlkit.dumps(doc), findings
