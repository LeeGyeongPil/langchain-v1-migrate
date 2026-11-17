"""LibCST based import rewriting for Python source.

Only import statements are touched. Every other byte of the file is kept,
including comments, blank lines and line endings. Running the rewrite on its
own output changes nothing (idempotent).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from langchain_v1_migrate.findings import Finding
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.legacy import LEGACY_NAMES, is_hub
from langchain_v1_migrate.table.load import MoveTable, Resolution


@dataclass
class Needs:
    """Packages the migrated code needs installed."""

    classic: bool = False
    community_extra: bool = False  # classic re-exports a community class
    community_direct: bool = False  # code imports langchain_community directly (``--target direct``)
    text_splitters: bool = False
    sqlalchemy: bool = False

    def merge(self, other: "Needs") -> None:
        for name in ("classic", "community_extra", "community_direct", "text_splitters", "sqlalchemy"):
            setattr(self, name, getattr(self, name) or getattr(other, name))

    def any(self) -> bool:
        return self.classic or self.community_direct or self.text_splitters or self.sqlalchemy


@dataclass
class RewriteResult:
    source: str
    findings: list[Finding]
    needs: Needs

    @property
    def changed(self) -> bool:
        return self.source != self._original

    _original: str = ""


# --------------------------------------------------------------------------- #
# small CST helpers
# --------------------------------------------------------------------------- #


def _dotted(node: cst.BaseExpression | None) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr.value}"
    return None


def _to_node(dotted: str) -> cst.Name | cst.Attribute:
    parts = dotted.split(".")
    node: cst.Name | cst.Attribute = cst.Name(parts[0])
    for part in parts[1:]:
        node = cst.Attribute(value=node, attr=cst.Name(part))
    return node


def _alias_name(alias: cst.ImportAlias) -> str:
    return _dotted(alias.name) or ""


def _alias_text(alias: cst.ImportAlias) -> str:
    text = _alias_name(alias)
    if alias.asname and isinstance(alias.asname.name, cst.Name):
        text += f" as {alias.asname.name.value}"
    return text


def _is_langchain_module(module: str | None) -> bool:
    return bool(module) and (module == "langchain" or module.startswith("langchain."))  # type: ignore[union-attr]


def _is_classic_module(module: str | None) -> bool:
    return bool(module) and (module == "langchain_classic" or module.startswith("langchain_classic."))  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# the transformer
# --------------------------------------------------------------------------- #


class Migrator(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, table: MoveTable, target: str, path: str, cell: int = 0):
        super().__init__()
        self.table = table
        self.target = target
        self.path = path
        self.cell = cell
        self.findings: list[Finding] = []
        self.needs = Needs()

    # -- reporting ---------------------------------------------------------- #

    def _report(self, code: str, node: cst.CSTNode, key: str | None = None, old: str = "", new: str = "", **values: object) -> None:
        pos = self.get_metadata(PositionProvider, node).start
        message = t(key or f"msg.{code}", **values)
        self.findings.append(Finding(code, self.path, pos.line, pos.column + 1, message, old, new, cell=self.cell))

    def _note_dest(self, res: Resolution) -> None:
        root = res.module.split(".")[0]
        if root == "langchain_classic":
            self.needs.classic = True
            if res.shim:
                self.needs.community_extra = True
            if "sqlalchemy_asyncio" in res.extras:
                self.needs.sqlalchemy = True
        elif root == "langchain_community":
            self.needs.community_direct = True
        elif root == "langchain_text_splitters":
            self.needs.text_splitters = True

    # -- statements --------------------------------------------------------- #

    def leave_SimpleStatementLine(self, original: cst.SimpleStatementLine, updated: cst.SimpleStatementLine):
        return self._body(original, updated, line=True)

    def leave_SimpleStatementSuite(self, original: cst.SimpleStatementSuite, updated: cst.SimpleStatementSuite):
        return self._body(original, updated, line=False)

    def _body(self, original, updated, line: bool):
        pieces: list[list[cst.BaseSmallStatement]] = []
        changed = False
        for orig_stmt, upd_stmt in zip(original.body, updated.body):
            if isinstance(upd_stmt, cst.ImportFrom):
                repl = self._from_import(orig_stmt, upd_stmt)
            elif isinstance(upd_stmt, cst.Import):
                repl = [self._plain_import(orig_stmt, upd_stmt)]
            else:
                repl = [upd_stmt]
            if len(repl) != 1 or repl[0] is not upd_stmt:
                changed = True
            pieces.append(repl)
        if not changed:
            return updated

        # A single import that had to be split becomes several lines.
        if line and len(pieces) == 1 and len(pieces[0]) > 1:
            stmts = pieces[0]
            first = updated.with_changes(body=[stmts[0].with_changes(semicolon=cst.MaybeSentinel.DEFAULT)])
            rest = [cst.SimpleStatementLine(body=[s.with_changes(semicolon=cst.MaybeSentinel.DEFAULT)]) for s in stmts[1:]]
            return cst.FlattenSentinel([first, *rest])

        # Otherwise keep one line and join pieces with ``;``.
        body: list[cst.BaseSmallStatement] = []
        for orig_stmt, repl in zip(original.body, pieces):
            for j, stmt in enumerate(repl):
                last_piece = j == len(repl) - 1
                if last_piece:
                    stmt = stmt.with_changes(semicolon=orig_stmt.semicolon)
                else:
                    stmt = stmt.with_changes(semicolon=cst.Semicolon(whitespace_after=cst.SimpleWhitespace(" ")))
                body.append(stmt)
        return updated.with_changes(body=body)

    # -- import x.y ---------------------------------------------------------- #

    def _plain_import(self, orig: cst.Import, upd: cst.Import) -> cst.Import:
        names = list(upd.names)
        changed = False
        for i, alias in enumerate(upd.names):
            module = _alias_name(alias)
            if _is_classic_module(module):
                self.needs.classic = True
                for flag in self.table.classic_extras(module):
                    if flag == "sqlalchemy_asyncio":
                        self.needs.sqlalchemy = True
                continue
            if not _is_langchain_module(module) or module == "langchain":
                continue
            res = self.table.resolve_module(module)
            if res.status == "gone-module":
                self._report("LCM004", orig, module=module, old=module)
            elif res.status == "move":
                if alias.asname is None:
                    self._report("LCM005", orig, "msg.LCM005.bare", old=module, module=module, new=res.module)
                else:
                    names[i] = alias.with_changes(name=_to_node(res.module))
                    changed = True
                    self._note_dest(res)
                    self._report("LCM001", orig, old=module, new=res.module, old_path=module, new_path=res.module)
                    if "sqlalchemy_asyncio" in res.extras:
                        self._report("LCM007", orig, module=res.module)
        if not changed:
            return upd
        return upd.with_changes(names=names)

    # -- from x import y ------------------------------------------------------ #

    def _from_import(self, orig: cst.ImportFrom, upd: cst.ImportFrom) -> list[cst.BaseSmallStatement]:
        if upd.relative:
            return [upd]
        module = _dotted(upd.module)
        if module == "langgraph.prebuilt" and not isinstance(upd.names, cst.ImportStar):
            for alias in upd.names:
                if _alias_name(alias) == "create_react_agent":
                    self._report("LCM009", orig, "msg.LCM009.react", old="create_react_agent", name="create_react_agent")
            return [upd]
        if _is_classic_module(module):
            self._existing_classic(orig, upd, module or "")
            return [upd]
        if not _is_langchain_module(module):
            return [upd]
        assert module is not None
        if isinstance(upd.names, cst.ImportStar):
            return self._star(orig, upd, module)
        return self._names(orig, upd, module)

    def _existing_classic(self, orig: cst.ImportFrom, upd: cst.ImportFrom, module: str) -> None:
        self.needs.classic = True
        if "sqlalchemy_asyncio" in self.table.classic_extras(module):
            self.needs.sqlalchemy = True
        if isinstance(upd.names, cst.ImportStar):
            return
        for alias in upd.names:
            name = _alias_name(alias)
            origin = self.table.origin_of(module, name)
            if origin and origin[0].split(".")[0] == "langchain_community":
                self.needs.community_extra = True
            if is_hub(module, name):
                self._report("LCM008", orig, old=f"{module}.{name}")
            if name in LEGACY_NAMES:
                self._report("LCM009", orig, old=name, name=name)

    def _star(self, orig, upd, module: str):
        res = self.table.resolve_module(module)
        if res.status == "gone-module":
            self._report("LCM004", orig, module=module, old=module)
            return [upd]
        if res.status == "move":
            self._note_dest(res)
            self._report("LCM001", orig, old=module, new=res.module, old_path=module, new_path=res.module)
            if "sqlalchemy_asyncio" in res.extras:
                self._report("LCM007", orig, module=res.module)
            return [upd.with_changes(module=_to_node(res.module))]
        if self.table.kind(module) == "partial":
            self._report("LCM005", orig, "msg.LCM005.star", old=f"from {module} import *", module=module)
        return [upd]

    def _names(self, orig: cst.ImportFrom, upd: cst.ImportFrom, module: str) -> list[cst.BaseSmallStatement]:
        aliases = list(upd.names)
        results: list[Resolution] = []
        for alias in aliases:
            results.append(self.table.resolve(module, _alias_name(alias), self.target))

        if all(r.status == "untouched" for r in results):
            return [upd]
        if self.table.kind(module) == "gone":
            self._report("LCM004", orig, module=module, old=module)
            return [upd]

        # group the aliases by destination module, in order of first appearance
        groups: list[tuple[str, list[cst.ImportAlias]]] = []
        moved_text: list[str] = []
        shim_names: list[str] = []
        dead_names: list[str] = []
        sqlalchemy_modules: list[str] = []
        for alias, res in zip(aliases, results):
            name = _alias_name(alias)
            if res.status == "move":
                self._note_dest(res)
                dest = res.module
                if res.name != name:
                    alias = alias.with_changes(name=cst.Name(res.name))
                    if alias.asname is None:
                        alias = alias.with_changes(asname=cst.AsName(name=cst.Name(name)))
                moved_text.append(f"{res.module}.{res.name}" if res.name else res.module)
                if res.dead:
                    dead_names.append(name)
                elif res.shim:
                    shim_names.append(name)
                if "sqlalchemy_asyncio" in res.extras and res.module not in sqlalchemy_modules:
                    sqlalchemy_modules.append(res.module)
                if is_hub(res.module, res.name):
                    self._report("LCM008", orig, old=f"{module}.{name}", new=f"{res.module}.{res.name}")
            else:
                dest = module  # kept or unresolved names stay where they are
                if res.status == "gone-name":
                    self._report("LCM003", orig, old=f"{module}.{name}", name=name, module=module)
                elif res.status == "keep" and is_hub(module, name):
                    self._report("LCM008", orig, old=f"{module}.{name}")
            for gmod, members in groups:
                if gmod == dest:
                    members.append(alias)
                    break
            else:
                groups.append((dest, [alias]))
            final_name = res.name if res.status == "move" and res.name else name
            if final_name in LEGACY_NAMES:
                self._report("LCM009", orig, old=name, name=name)

        if not moved_text:
            return [upd]
        if len(groups) == 1:
            new_mod = groups[0][0]
            new_nodes = [upd.with_changes(module=_to_node(new_mod), names=_rename_aliases(upd, results, aliases))]
            code, old_text, new_text = "LCM001", module, new_mod
            self._report(code, orig, old=old_text, new=new_text, old_path=module, new_path=new_mod)
        else:
            new_nodes = self._split(upd, groups)
            targets = "; ".join(f"{m}: {', '.join(_alias_text(a) for a in members)}" for m, members in groups)
            self._report("LCM002", orig, old=module, new=targets, module=module, targets=targets)
        if shim_names:
            self._report("LCM006", orig, names=", ".join(shim_names), old=module)
        if dead_names:
            self._report("LCM006", orig, "msg.LCM006.dead", names=", ".join(dead_names), old=module)
        for smod in sqlalchemy_modules:
            self._report("LCM007", orig, module=smod)
        return new_nodes

    def _split(self, upd: cst.ImportFrom, groups: Sequence[tuple[str, list[cst.ImportAlias]]]) -> list[cst.BaseSmallStatement]:
        out: list[cst.BaseSmallStatement] = []
        original_last = upd.names[-1] if not isinstance(upd.names, cst.ImportStar) else None
        for index, (dest, members) in enumerate(groups):
            names = []
            for j, alias in enumerate(members):
                is_last = j == len(members) - 1
                if is_last:
                    keep_comma = index == 0 and upd.lpar is not None and alias.comma is not cst.MaybeSentinel.DEFAULT and _is_original_last(alias, original_last)
                    alias = alias if keep_comma else alias.with_changes(comma=cst.MaybeSentinel.DEFAULT)
                elif index > 0:
                    alias = alias.with_changes(comma=cst.Comma(whitespace_after=cst.SimpleWhitespace(" ")))
                names.append(alias)
            if index == 0:
                out.append(upd.with_changes(module=_to_node(dest), names=names))
            else:  # later lines use plain one-line formatting
                out.append(
                    cst.ImportFrom(
                        module=_to_node(dest),
                        names=names,
                    )
                )
        return out


def _is_original_last(alias: cst.ImportAlias, original_last: cst.ImportAlias | None) -> bool:
    return original_last is not None and alias.deep_equals(original_last)


def _rename_aliases(upd: cst.ImportFrom, results: list[Resolution], aliases: list[cst.ImportAlias]):
    """Apply ``--target direct`` renames when the origin name differs (rare)."""
    out = []
    for alias, res in zip(aliases, results):
        name = _alias_name(alias)
        if res.status == "move" and res.name and res.name != name:
            alias = alias.with_changes(name=cst.Name(res.name))
            if alias.asname is None:
                alias = alias.with_changes(asname=cst.AsName(name=cst.Name(name)))
        out.append(alias)
    return out


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def rewrite_source(source: str, path: str, table: MoveTable, target: str = "classic", cell: int = 0) -> RewriteResult:
    """Rewrite one Python source string.

    Returns the new source (identical to the input when nothing changed), the
    findings and the packages the migrated code needs. A syntax error becomes
    a ``LCM011`` finding and leaves the source untouched.
    """
    bom = source.startswith("﻿")
    text = source[1:] if bom else source
    try:
        module = cst.parse_module(text)
    except cst.ParserSyntaxError as exc:
        finding = Finding(
            "LCM011", path, exc.raw_line, exc.raw_column + 1,
            t("msg.LCM011", detail=exc.message), cell=cell,
        )
        return RewriteResult(source, [finding], Needs(), _original=source)
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    migrator = Migrator(table, target, path, cell)
    new_module = wrapper.visit(migrator)
    new_source = ("﻿" if bom else "") + new_module.code
    findings = sorted(migrator.findings, key=lambda f: (f.line, f.col, f.code))
    return RewriteResult(new_source, findings, migrator.needs, _original=source)
