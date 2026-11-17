"""Command line entry point: check / fix / lookup / table."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from langchain_v1_migrate import __version__, engine, i18n, report
from langchain_v1_migrate.findings import summarize
from langchain_v1_migrate.i18n import t
from langchain_v1_migrate.table import compute, load
from langchain_v1_migrate.walk import PathError, collect

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _add_common(p: argparse.ArgumentParser, paths: bool = True) -> None:
    if paths:
        p.add_argument("paths", nargs="*", default=["."], metavar="PATH", help=t("help.paths"))
        p.add_argument("--exclude", action="append", default=[], metavar="GLOB", help=t("help.exclude"))
    p.add_argument("--target", choices=load.TARGETS, default="classic", help=t("help.target"))
    p.add_argument("--table", metavar="FILE", help=t("help.table"))
    p.add_argument("--lang", choices=i18n.LANGUAGES, default=argparse.SUPPRESS, help=t("help.lang"))


class _Formatter(argparse.RawDescriptionHelpFormatter):
    """Raw description plus a translated "usage:" prefix."""

    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = t("help.usage") + " "
        super().add_usage(usage, actions, groups, prefix)


def _localize(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Translate argparse's built-in -h text and section titles (argparse has no hook for them)."""
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help=t("help.help"))
    parser._positionals.title = t("help.positionals")  # type: ignore[attr-defined]
    parser._optionals.title = t("help.options")  # type: ignore[attr-defined]
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="langchain-v1-migrate",
        description=t("help.description"),
        epilog=t("help.epilog"),
        formatter_class=_Formatter,
        add_help=False,
    )
    _localize(parser)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}", help=t("help.version"))
    parser.add_argument("--lang", choices=i18n.LANGUAGES, default=None, help=t("help.lang"))
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    check = _localize(sub.add_parser("check", help=t("help.check"), description=t("help.check"), formatter_class=_Formatter, add_help=False))
    _add_common(check)
    check.add_argument("--format", choices=("text", "json"), default="text", help=t("help.format"))
    check.add_argument("--strict", action="store_true", help=t("help.strict"))

    fix = _localize(sub.add_parser("fix", help=t("help.fix"), description=t("help.fix"), formatter_class=_Formatter, add_help=False))
    _add_common(fix)
    fix.add_argument("--write", action="store_true", help=t("help.write"))
    fix.add_argument("--no-deps", action="store_true", help=t("help.no_deps"))

    lookup = _localize(sub.add_parser("lookup", help=t("help.lookup"), description=t("help.lookup"), formatter_class=_Formatter, add_help=False))
    lookup.add_argument("name", metavar="NAME", help=t("help.name"))
    _add_common(lookup, paths=False)

    table = _localize(sub.add_parser("table", help=t("help.table_cmd"), description=t("help.table_cmd"), formatter_class=_Formatter, add_help=False))
    table.add_argument("--from-site", required=True, metavar="DIR", help=t("help.from_site"))
    table.add_argument("--to-site", required=True, metavar="DIR", help=t("help.to_site"))
    table.add_argument("--community-site", metavar="DIR", help=t("help.community_site"))
    table.add_argument("-o", "--output", metavar="FILE", help=t("help.output"))
    table.add_argument("--computed-on", metavar="DATE", help=t("help.computed_on"))
    table.add_argument("--lang", choices=i18n.LANGUAGES, default=argparse.SUPPRESS, help=t("help.lang"))
    return parser


def _load_table(path: str | None) -> load.MoveTable:
    return load.from_file(path) if path else load.bundled()


def _paths_or_exit(args: argparse.Namespace):
    try:
        return collect(args.paths, tuple(args.exclude))
    except PathError as exc:
        print(t("error.path", path=str(exc)), file=sys.stderr)
        return None


def cmd_check(args: argparse.Namespace) -> int:
    table = _load_table(args.table)
    targets = _paths_or_exit(args)
    if targets is None:
        return EXIT_USAGE
    result = engine.run(targets, table, args.target)
    if args.format == "json":
        sys.stdout.write(report.render_json(result.findings, result.files, table, args.target))
    else:
        sys.stdout.write(report.render_text(result.findings, result.files, table))
    summary = summarize(result.findings, result.files)
    if summary["fixable"] or summary["errors"] or (args.strict and summary["warnings"]):
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_fix(args: argparse.Namespace) -> int:
    table = _load_table(args.table)
    targets = _paths_or_exit(args)
    if targets is None:
        return EXIT_USAGE
    result = engine.run(targets, table, args.target, with_deps=not args.no_deps)
    if args.write:
        for path, (_old, new) in result.changes.items():
            path.write_bytes(new.encode("utf-8"))
        print(t("fix.written", count=len(result.changes)))
    else:
        sys.stdout.write(report.render_diff(result.changes))
        print(t("fix.preview", count=len(result.changes)), file=sys.stderr)
    remaining = [f for f in result.findings if f.severity == "error"]
    for f in remaining:
        where = f"{f.path}:cell{f.cell}:{f.line}" if f.cell else f"{f.path}:{f.line}"
        print(f"{where}: {f.code} {f.message}", file=sys.stderr)
    return EXIT_FINDINGS if remaining else EXIT_OK


def cmd_lookup(args: argparse.Namespace) -> int:
    table = _load_table(args.table)
    name = args.name.strip()
    module, attr = name, ""
    if table.kind(name) is None:
        module, _, attr = name.rpartition(".")
    if not module or table.kind(module) in (None, "new"):
        print(t("lookup.unknown", name=name), file=sys.stderr)
        return EXIT_USAGE

    def one(target: str) -> load.Resolution:
        return table.resolve(module, attr, target) if attr else table.resolve_module(module)

    primary = one(args.target)
    print(name)
    if primary.status == "gone-module":
        print("  " + t("lookup.gone_module", module=module))
        print("  " + t("lookup.hint"))
        return EXIT_FINDINGS
    if primary.status == "gone-name":
        print("  " + t("lookup.gone_name", name=attr, module=module))
        return EXIT_FINDINGS
    if primary.status == "keep":
        print("  " + t("lookup.keep", path=f"{module}.{attr}" if attr else module))
        return EXIT_OK
    for target in load.TARGETS:
        res = one(target)
        text = f"{res.module}.{res.name}" if res.name else res.module
        marker = "*" if target == args.target else " "
        print(f"  {marker} {target:<8} {text}")
    chosen = primary
    needs = []
    if chosen.distribution:
        needs.append(chosen.distribution)
    if chosen.shim:
        needs.append("langchain-community  (" + t("lookup.shim") + ")")
    if "sqlalchemy_asyncio" in chosen.extras:
        needs.append("sqlalchemy[asyncio]")
    if chosen.dead:
        print("  " + t("lookup.dead"))
    if needs:
        print("  " + t("lookup.needs", needs=", ".join(needs)))
    return EXIT_OK


def cmd_table(args: argparse.Namespace) -> int:
    try:
        data = compute.build_table(
            Path(args.from_site),
            Path(args.to_site),
            args.computed_on,
            Path(args.community_site) if args.community_site else None,
        )
    except compute.TableError as exc:
        print(t("error.table", detail=str(exc)), file=sys.stderr)
        return EXIT_USAGE
    c = data["counts"]
    print(t("table.versions", table=report.table_label(load.MoveTable(data))))
    print(t("table.counts", move=c["move"], partial=c["partial"], gone=c["gone"], keep=c["keep"], names=c["partial_names_moved"]))
    if args.output:
        compute.write_table(data, Path(args.output))
        print(t("table.written", path=args.output))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.set_lang(i18n.resolve_lang(i18n.lang_from_argv(argv)))
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "lang", None):
        i18n.set_lang(args.lang)
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE
    try:
        handler = {"check": cmd_check, "fix": cmd_fix, "lookup": cmd_lookup, "table": cmd_table}[args.command]
        return handler(args)
    except ValueError as exc:  # unreadable --table file
        print(t("error.generic", detail=str(exc)), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
