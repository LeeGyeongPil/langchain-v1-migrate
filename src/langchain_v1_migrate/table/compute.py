"""Compute the move table from two installed package trees.

Nothing is imported or executed: every module is read with :mod:`ast`.

Inputs are two ``site-packages`` directories:

* the *old* one holds ``langchain`` 0.3.x
* the *new* one holds ``langchain`` 1.x and ``langchain_classic``

The result classifies every old module as ``keep``, ``partial`` (module kept but
only some names), ``move`` (now lives in ``langchain_classic``) or ``gone``, and
records where classic re-exports names from (core, text-splitters, community)
and which extra dependencies importing a classic module needs.
"""

from __future__ import annotations

import ast
import gzip
import json
from pathlib import Path
from typing import Any

SCHEMA = 1
CLASSIC = "langchain_classic"


class TableError(Exception):
    """Raised when a package tree needed for the table is missing."""


# --------------------------------------------------------------------------- #
# Reading one package tree
# --------------------------------------------------------------------------- #


def _literal_strs(node: ast.AST) -> list[str] | None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def _is_type_checking(test: ast.AST) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _module_level(body: list[ast.stmt], include_try: bool) -> list[ast.stmt]:
    """Statements that run when the module is imported (TYPE_CHECKING blocks excluded)."""
    out: list[ast.stmt] = []
    for st in body:
        if isinstance(st, ast.If):
            if _is_type_checking(st.test):
                out.extend(_module_level(st.orelse, include_try))
            else:
                out.extend(_module_level(st.body, include_try))
                out.extend(_module_level(st.orelse, include_try))
        elif isinstance(st, ast.Try):
            if include_try:
                out.extend(_module_level(st.body, include_try))
        else:
            out.append(st)
    return out


def _is_lookup_table(node: ast.Dict) -> bool:
    """``{"Name": "langchain_x.module"}``: a lazy-import table served by ``__getattr__``."""
    if not node.keys:
        return False
    for key, value in zip(node.keys, node.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return False
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.startswith("langchain")):
            return False
    return True


def _symbols(tree: ast.Module) -> tuple[list[str], set[str]]:
    """Public names of a module and the set of every name it binds."""
    all_names: list[str] | None = None
    bound: set[str] = set()
    lazy: set[str] = set()
    for st in tree.body:
        if isinstance(st, ast.Assign):
            for target in st.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = _literal_strs(st.value)
                    if value is not None:
                        all_names = value
                elif isinstance(target, ast.Name):
                    bound.add(target.id)
                    if isinstance(st.value, ast.Dict) and _is_lookup_table(st.value):
                        for key in st.value.keys:
                            lazy.add(key.value)  # type: ignore[union-attr]
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            bound.add(st.target.id)
        elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(st.name)
        elif isinstance(st, ast.ImportFrom):
            for alias in st.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(st, ast.Import):
            for alias in st.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(st, ast.If):
            for inner in st.body:
                if isinstance(inner, ast.ImportFrom):
                    for alias in inner.names:
                        bound.add(alias.asname or alias.name)
    base = set(all_names) if all_names is not None else {n for n in bound if not n.startswith("_")}
    public = sorted(base | {n for n in lazy if not n.startswith("_")})
    return public, bound


def _absolute(module: str | None, level: int, current: str, is_package: bool) -> str | None:
    if level == 0:
        return module
    parts = current.split(".")
    if not is_package:
        parts = parts[:-1]
    if level - 1 > len(parts) - 1:
        return None
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    if module:
        parts = parts + module.split(".")
    return ".".join(parts)


def _origins(tree: ast.Module, public: list[str], bound: set[str], current: str, is_package: bool) -> dict[str, list[str]]:
    """Names this module only re-exports from another ``langchain_*`` distribution."""
    origins: dict[str, list[str]] = {}

    # (a) plain top-level ``from langchain_core.x import Name``
    for st in _module_level(tree.body, include_try=True):
        if not isinstance(st, ast.ImportFrom):
            continue
        source = _absolute(st.module, st.level, current, is_package)
        if not source or not source.startswith("langchain_") or source.split(".")[0] == CLASSIC:
            continue
        for alias in st.names:
            if alias.name != "*":
                origins[alias.asname or alias.name] = [source, alias.name]

    # (b) lookup tables: DEPRECATED_LOOKUP = {"FAISS": "langchain_community.vectorstores"}
    for st in tree.body:
        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Dict) and _is_lookup_table(st.value):
            for key, value in zip(st.value.keys, st.value.values):
                source = value.value  # type: ignore[union-attr]
                if source.startswith("langchain_") and source.split(".")[0] != CLASSIC:
                    origins[key.value] = [source, key.value]  # type: ignore[union-attr]

    # (c) module __getattr__ that delegates to langchain_community
    delegate = None
    for st in tree.body:
        if isinstance(st, ast.FunctionDef) and st.name == "__getattr__":
            for inner in ast.walk(st):
                if isinstance(inner, ast.ImportFrom) and inner.module and inner.module.split(".")[0] == "langchain_community":
                    if inner.module == "langchain_community" and inner.names:
                        delegate = "langchain_community." + inner.names[0].name
                    else:
                        delegate = inner.module
    if delegate:
        for name in public:
            if name not in bound and name not in origins:
                origins[name] = [delegate, name]
    return origins


def _flag_imports(tree: ast.Module, current: str, is_package: bool) -> list[tuple[str, list[str]]]:
    out = []
    for st in _module_level(tree.body, include_try=False):
        if isinstance(st, ast.ImportFrom):
            source = _absolute(st.module, st.level, current, is_package)
            if source:
                out.append((source, [a.name for a in st.names]))
        elif isinstance(st, ast.Import):
            for alias in st.names:
                out.append((alias.name, []))
    return out


def enumerate_modules(site: Path, package: str) -> dict[str, dict[str, Any]]:
    """Read every module of ``package`` under ``site`` without importing it."""
    root = site / package
    if not root.is_dir():
        raise TableError(f"package '{package}' not found under {site}")
    result: dict[str, dict[str, Any]] = {}
    for py in sorted(root.rglob("*.py")):
        parts = list(py.relative_to(site).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        module = ".".join(parts)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            result[module] = {"symbols": [], "origins": {}, "imports": []}
            continue
        public, bound = _symbols(tree)
        result[module] = {
            "symbols": public,
            "origins": _origins(tree, public, bound, module, is_package),
            "imports": _flag_imports(tree, module, is_package),
        }
    return result


# --------------------------------------------------------------------------- #
# Extra dependencies needed when importing a classic module
# --------------------------------------------------------------------------- #


def _direct_flags(imports: list[tuple[str, list[str]]]) -> set[str]:
    flags: set[str] = set()
    for source, names in imports:
        root = source.split(".")[0]
        if root == "langchain_community":
            flags.add("community")
        elif root == "sqlalchemy" and (
            source.startswith("sqlalchemy.ext.asyncio") or (source == "sqlalchemy.ext" and "asyncio" in names)
        ):
            flags.add("sqlalchemy_asyncio")
    return flags


def _extras(classic: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    own = {mod: _direct_flags(info["imports"]) for mod, info in classic.items()}
    edges: dict[str, set[str]] = {}
    for mod, info in classic.items():
        targets: set[str] = set()
        for source, names in info["imports"]:
            if source.split(".")[0] != CLASSIC:
                continue
            for candidate in [source] + [f"{source}.{n}" for n in names]:
                if candidate in classic:
                    targets.add(candidate)
            # importing a module also runs its parent packages
            parts = source.split(".")
            for i in range(1, len(parts)):
                if ".".join(parts[:i]) in classic:
                    targets.add(".".join(parts[:i]))
        parts = mod.split(".")
        for i in range(1, len(parts)):
            if ".".join(parts[:i]) in classic:
                targets.add(".".join(parts[:i]))
        targets.discard(mod)
        edges[mod] = targets

    result: dict[str, list[str]] = {}
    for mod in classic:
        seen = {mod}
        stack = [mod]
        flags: set[str] = set()
        while stack:
            cur = stack.pop()
            flags |= own[cur]
            for nxt in edges[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if flags:
            result[mod] = sorted(flags)
    return result


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classic_name(module: str) -> str:
    """``langchain.chains`` -> ``langchain_classic.chains``."""
    return CLASSIC + module[len("langchain"):]


def _dist_version(site: Path, dist: str) -> str:
    wanted = dist.replace("-", "_").lower()
    for path in sorted(site.glob("*.dist-info")):
        stem = path.name[: -len(".dist-info")]
        name, _, version = stem.rpartition("-")
        if name.replace("-", "_").lower() == wanted:
            return version
    raise TableError(f"distribution '{dist}' (*.dist-info) not found under {site}")


def _dead_origins(classic: dict[str, dict[str, Any]], community: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Names classic re-exports from langchain_community that community no longer defines."""
    dead: dict[str, list[str]] = {}
    for module, info in classic.items():
        for name, (source, original) in info["origins"].items():
            if source.split(".")[0] != "langchain_community":
                continue
            target = community.get(source)
            if target is None or original not in target["symbols"]:
                dead.setdefault(module, []).append(name)
    return {m: sorted(v) for m, v in sorted(dead.items())}


def build_table(
    old_site: Path,
    new_site: Path,
    computed_on: str | None = None,
    community_site: Path | None = None,
) -> dict[str, Any]:
    """Compute the whole move table. Deterministic for identical inputs.

    ``community_site`` (optional) is a site-packages folder with langchain-community;
    with it, re-exports whose target no longer exists there are recorded as ``dead``.
    """
    old_site, new_site = Path(old_site), Path(new_site)
    old = enumerate_modules(old_site, "langchain")
    new = enumerate_modules(new_site, "langchain")
    classic = enumerate_modules(new_site, CLASSIC)

    kinds: dict[str, str] = {}
    partial_moved = 0
    partial_gone = 0
    for module, info in old.items():
        cmod = classic_name(module)
        old_syms = set(info["symbols"])
        if module in new:
            missing = old_syms - set(new[module]["symbols"])
            if not missing:
                kinds[module] = "keep"
            else:
                kinds[module] = "partial"
                in_classic = missing & set(classic.get(cmod, {}).get("symbols", []))
                partial_moved += len(in_classic)
                partial_gone += len(missing) - len(in_classic)
        elif cmod in classic:
            kinds[module] = "move"
        else:
            kinds[module] = "gone"

    counts = {k: sum(1 for v in kinds.values() if v == k) for k in ("keep", "partial", "move", "gone")}
    counts["partial_names_moved"] = partial_moved
    counts["partial_names_gone"] = partial_gone

    meta: dict[str, Any] = {
        "from": {"langchain": _dist_version(old_site, "langchain")},
        "to": {
            "langchain": _dist_version(new_site, "langchain"),
            "langchain-classic": _dist_version(new_site, "langchain-classic"),
        },
    }
    dead: dict[str, list[str]] = {}
    if community_site is not None:
        community_site = Path(community_site)
        community = enumerate_modules(community_site, "langchain_community")
        meta["to"]["langchain-community"] = _dist_version(community_site, "langchain-community")
        dead = _dead_origins(classic, community)
    if computed_on:
        meta["computed_on"] = computed_on

    return {
        "schema": SCHEMA,
        "meta": meta,
        "counts": counts,
        "old": dict(sorted(kinds.items())),
        "new": {m: i["symbols"] for m, i in sorted(new.items())},
        "classic": {m: i["symbols"] for m, i in sorted(classic.items())},
        "origins": {m: dict(sorted(i["origins"].items())) for m, i in sorted(classic.items()) if i["origins"]},
        "extras": dict(sorted(_extras(classic).items())),
        "dead": dead,
    }


def dumps(table: dict[str, Any], pretty: bool = False) -> bytes:
    """Stable serialisation (sorted keys) used for hashing and storage."""
    if pretty:
        return (json.dumps(table, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return json.dumps(table, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_table(table: dict[str, Any], path: Path) -> None:
    """Write ``path``; a ``.gz`` suffix gzips with a fixed timestamp (byte-stable)."""
    path = Path(path)
    if path.suffix == ".gz":
        with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(dumps(table))
    else:
        path.write_bytes(dumps(table, pretty=True))
