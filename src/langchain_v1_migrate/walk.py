"""Find the files to look at."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".ipynb_checkpoints",
    "*.egg-info",
)


@dataclass
class Targets:
    python: list[Path] = field(default_factory=list)
    notebooks: list[Path] = field(default_factory=list)
    requirements: list[Path] = field(default_factory=list)
    pyprojects: list[Path] = field(default_factory=list)

    def total_sources(self) -> int:
        return len(self.python) + len(self.notebooks)


class PathError(Exception):
    """A given path does not exist."""


def _excluded(name: str, rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, p) or fnmatch.fnmatch(rel, p) for p in patterns)


def _classify(path: Path, out: Targets) -> None:
    name = path.name
    if name.endswith(".py"):
        out.python.append(path)
    elif name.endswith(".ipynb"):
        out.notebooks.append(path)
    elif name == "pyproject.toml":
        out.pyprojects.append(path)
    elif name.startswith("requirements") and name.endswith(".txt"):
        out.requirements.append(path)


def collect(paths: list[str], excludes: tuple[str, ...] = ()) -> Targets:
    """Walk ``paths`` (files or folders) and sort the interesting files by kind.

    Explicitly named files are always included; ``excludes`` and the default
    exclude list only apply while walking folders.
    """
    patterns = DEFAULT_EXCLUDES + tuple(excludes)
    out = Targets()
    seen: set[Path] = set()
    for raw in paths:
        root = Path(raw)
        if not root.exists():
            raise PathError(raw)
        if root.is_file():
            if root.resolve() not in seen:
                seen.add(root.resolve())
                _classify(root, out)
            continue
        for current, dirs, files in os.walk(root):
            base = Path(current)
            dirs[:] = sorted(d for d in dirs if not _excluded(d, str((base / d).relative_to(root)), patterns))
            for fname in sorted(files):
                rel = str((base / fname).relative_to(root))
                if _excluded(fname, rel, tuple(excludes)):
                    continue
                candidate = base / fname
                if candidate.resolve() in seen:
                    continue
                seen.add(candidate.resolve())
                _classify(candidate, out)
    return out
