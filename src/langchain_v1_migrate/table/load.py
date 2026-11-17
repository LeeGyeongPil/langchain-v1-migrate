"""Load a move table and answer "where did this name go?" questions."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from langchain_v1_migrate.table.compute import CLASSIC, classic_name

#: ``--target`` values. ``classic`` follows the official guide; ``direct``
#: follows re-export shims to the package that really defines the name.
TARGETS = ("classic", "direct")

#: distribution name for an import root
DISTRIBUTIONS = {
    "langchain_classic": "langchain-classic",
    "langchain_community": "langchain-community",
    "langchain_text_splitters": "langchain-text-splitters",
    "langchain_core": "langchain-core",
}


@dataclass(frozen=True)
class Resolution:
    """Outcome for one imported name (or one module).

    ``status`` is one of ``keep`` (stays in langchain 1.x), ``move`` (new
    location in ``module``/``name``), ``gone-name`` (the module still exists
    but the name does not), ``gone-module`` (the module is not in 1.x at all),
    ``untouched`` (not something this tool knows about).
    """

    status: str
    module: str
    name: str
    shim: bool = False  # classic re-exports it from langchain-community
    dead: bool = False  # ... but the installed langchain-community no longer defines it
    extras: tuple[str, ...] = field(default_factory=tuple)  # e.g. ("sqlalchemy_asyncio",)

    @property
    def distribution(self) -> str | None:
        root = self.module.split(".")[0]
        return DISTRIBUTIONS.get(root)


class MoveTable:
    """Read-only view over a table produced by :func:`compute.build_table`."""

    def __init__(self, data: dict[str, Any]):
        if data.get("schema") != 1:
            raise ValueError("unsupported move table schema; recompute it with the 'table' command")
        self.data = data
        self.meta = data["meta"]
        self.counts = data["counts"]
        self._old: dict[str, str] = data["old"]
        self._new: dict[str, list[str]] = data["new"]
        self._classic: dict[str, list[str]] = data["classic"]
        self._origins: dict[str, dict[str, list[str]]] = data["origins"]
        self._extras: dict[str, list[str]] = data["extras"]
        self._dead: dict[str, frozenset[str]] = {m: frozenset(v) for m, v in data.get("dead", {}).items()}
        self._classic_sets: dict[str, frozenset[str]] = {}

    # -- index helpers ----------------------------------------------------- #

    def _names(self, module: str) -> frozenset[str]:
        cached = self._classic_sets.get(module)
        if cached is None:
            cached = frozenset(self._classic.get(module, []))
            self._classic_sets[module] = cached
        return cached

    def kind(self, module: str) -> str | None:
        """``keep`` / ``partial`` / ``move`` / ``gone`` for a 0.3 module, ``new`` for a 1.x-only one."""
        if module in self._old:
            return self._old[module]
        if module in self._new:
            return "new"
        return None

    def exists_in_new(self, module: str, name: str | None = None) -> bool:
        """Is ``module`` (and ``name`` in it) present in langchain 1.x or langchain-classic?"""
        index = self._new if module in self._new else self._classic
        if module not in index:
            return False
        if name is None:
            return True
        return name in index[module] or f"{module}.{name}" in self._new or f"{module}.{name}" in self._classic

    def classic_extras(self, module: str) -> tuple[str, ...]:
        return tuple(self._extras.get(module, ()))

    # -- resolution --------------------------------------------------------- #

    def resolve_module(self, module: str) -> Resolution:
        """Where does ``import <module>`` (whole module) go?"""
        kind = self.kind(module)
        if kind is None or kind == "new":
            return Resolution("untouched", module, "")
        if kind == "gone":
            return Resolution("gone-module", module, "")
        if kind == "move":
            cmod = classic_name(module)
            return Resolution("move", cmod, "", extras=self.classic_extras(cmod))
        return Resolution("keep", module, "")

    def resolve(self, module: str, name: str, target: str = "classic") -> Resolution:
        """Where does ``from <module> import <name>`` go?"""
        kind = self.kind(module)
        if kind is None or kind == "new":
            return Resolution("untouched", module, name)
        if kind == "gone":
            return Resolution("gone-module", module, name)
        if kind in ("keep", "partial"):
            if name in self._new.get(module, ()) or f"{module}.{name}" in self._new:
                return Resolution("keep", module, name)
            if kind == "keep":
                return Resolution("keep", module, name)
        cmod = classic_name(module)
        if cmod not in self._classic:
            return Resolution("gone-name", module, name)
        if name in self._names(cmod) or f"{cmod}.{name}" in self._classic:
            origin = self._origins.get(cmod, {}).get(name)
            extras = self.classic_extras(cmod)
            shim = bool(origin) and origin[0].split(".")[0] == "langchain_community"
            dead = shim and name in self._dead.get(cmod, frozenset())
            if target == "direct" and origin:
                return Resolution("move", origin[0], origin[1], shim=False, dead=dead, extras=())
            return Resolution("move", cmod, name, shim=shim, dead=dead, extras=extras)
        return Resolution("gone-name", module, name)

    def origin_of(self, classic_module: str, name: str) -> list[str] | None:
        return self._origins.get(classic_module, {}).get(name)

    def old_modules(self) -> list[str]:
        return list(self._old)


@lru_cache(maxsize=1)
def bundled() -> MoveTable:
    """The table shipped inside the package."""
    with resources.files("langchain_v1_migrate.table").joinpath("data/move_table.json.gz").open("rb") as fh:
        return MoveTable(json.loads(gzip.decompress(fh.read()).decode("utf-8")))


def from_file(path: str | Path) -> MoveTable:
    """Load a table written by the ``table`` command (``.json`` or ``.json.gz``)."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read table file {path}: {exc.strerror}") from exc
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    try:
        return MoveTable(json.loads(raw.decode("utf-8")))
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"{path} is not a move table; create one with the 'table' command") from exc


__all__ = ["MoveTable", "Resolution", "TARGETS", "bundled", "from_file", "CLASSIC"]
