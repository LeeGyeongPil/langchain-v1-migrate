"""Check that the langchain imports in .py and .ipynb files really import.

Usage (needs langchain 1.x, langchain-classic[community] and sqlalchemy[asyncio]):

    python -I scripts/import_check.py examples/expected examples/expected-direct

Every ``import`` / ``from ... import`` statement whose top-level package starts
with ``langchain`` is executed on its own. Files whose first line is
``# import-check: skip`` are ignored. The last line is ``import ok: N/N``; the
exit code is 1 if any import failed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

SKIP_MARK = "# import-check: skip"


def statements(code: str) -> list[ast.stmt]:
    found: list[ast.stmt] = []
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("langchain"):
            found.append(node)
        elif isinstance(node, ast.Import) and any(a.name.startswith("langchain") for a in node.names):
            found.append(node)
    return found


def code_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".ipynb":
        cells = json.loads(text)["cells"]
        chunks = []
        for cell in cells:
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
            if src.lstrip().startswith("%%"):
                continue
            lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("%", "!")) and not ln.rstrip().endswith("?")]
            chunks.append("\n".join(lines))
        return "\n\n".join(chunks)
    return text


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: import_check.py FOLDER_OR_FILE [...]", file=sys.stderr)
        return 2
    files: list[Path] = []
    for raw in argv:
        root = Path(raw)
        if not root.exists():
            print(f"path does not exist: {raw}", file=sys.stderr)
            return 2
        files.extend([root] if root.is_file() else sorted([*root.rglob("*.py"), *root.rglob("*.ipynb")]))

    total = ok = 0
    failed: list[str] = []
    for path in files:
        code = code_of(path)
        if code.startswith(SKIP_MARK):
            print(f"skip {path}")
            continue
        for node in statements(code):
            total += 1
            text = ast.unparse(node)
            try:
                exec(compile(text, str(path), "exec"), {})
                ok += 1
            except Exception as exc:  # noqa: BLE001 - report every failure kind
                module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
                print(f"import failed: {module}  [{path}]  {type(exc).__name__}: {exc}")
                failed.append(module or "")
    print(f"import ok: {ok}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
