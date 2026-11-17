"""AC-5: notebooks keep magics, skip cell magics and keep their JSON layout."""

from __future__ import annotations

import json

from langchain_v1_migrate.notebook import mask_magics, process_notebook, unmask_magics, update_pip_lines
from langchain_v1_migrate.rewrite import Needs

from conftest import EXAMPLES

NB = EXAMPLES / "legacy" / "rag.ipynb"


def _run(table, text=None):
    text = NB.read_text(encoding="utf-8") if text is None else text
    return text, process_notebook(text, "rag.ipynb", table, "classic")


def _source(nb: dict, cell_id: str) -> str:
    cell = next(c for c in nb["cells"] if c["id"] == cell_id)
    return "".join(cell["source"])


def test_magics_preserved(table):
    _, result = _run(table)
    nb = json.loads(result.text)
    imports = _source(nb, "imports")
    assert imports.startswith("!pip list | grep langchain\n")  # shell escape untouched
    assert "from langchain_classic.chains import LLMChain\n" in imports
    assert "from langchain.agents import create_agent\n" in imports
    assert "from langchain_classic.agents import AgentExecutor\n" in imports
    help_cell = _source(nb, "help")
    assert help_cell.endswith("PromptTemplate?")  # IPython help suffix untouched
    assert "from langchain_classic.prompts import PromptTemplate" in help_cell
    assert _source(nb, "install") == "%pip install -qU langchain langchain-openai"  # pip lines are the deps step's job


def test_cell_magic_skipped(table):
    original, result = _run(table)
    nb = json.loads(result.text)
    assert _source(nb, "shell") == '%%bash\necho "from langchain.chains import LLMChain"'  # untouched
    skipped = [f for f in result.findings if f.code == "LCM010"]
    assert len(skipped) == 1 and skipped[0].cell == 5


def test_only_changed_cells_differ(table):
    original, result = _run(table)
    before, after = json.loads(original), json.loads(result.text)
    assert before["metadata"] == after["metadata"]
    assert (before["nbformat"], before["nbformat_minor"]) == (after["nbformat"], after["nbformat_minor"])
    changed = {a["id"] for a, b in zip(before["cells"], after["cells"]) if a != b}
    assert changed == {"imports", "help"}
    # outputs and counters of a changed cell are kept
    imports_before = next(c for c in before["cells"] if c["id"] == "imports")
    imports_after = next(c for c in after["cells"] if c["id"] == "imports")
    assert imports_before["outputs"] == imports_after["outputs"]
    assert imports_before["execution_count"] == imports_after["execution_count"]
    # file layout: same indent and trailing newline
    assert result.text.endswith("}\n")
    assert result.text.startswith('{\n "cells": [\n  {\n   "cell_type"')


def test_unchanged_notebook_is_returned_verbatim(table):
    text = json.dumps({"cells": [{"cell_type": "code", "source": ["x = 1\n"], "metadata": {}, "outputs": []}], "metadata": {}, "nbformat": 4, "nbformat_minor": 5})
    _, result = _run(table, text)
    assert result.text == text


def test_second_run_changes_nothing(table):
    _, first = _run(table)
    _, second = _run(table, first.text)
    assert second.text == first.text
    assert not any(f.fixable for f in second.findings)


def test_pip_line_gets_classic_once(table):
    original, result = _run(table)
    needs = result.needs
    text, findings = update_pip_lines(result.text, "rag.ipynb", needs)
    nb = json.loads(text)
    assert _source(nb, "install") == "%pip install -qU langchain langchain-openai langchain-classic"
    assert text.count("langchain-classic") == result.text.count("langchain-classic") + 1
    assert [f.code for f in findings] == ["LCM013"] and findings[0].cell == 2
    again, more = update_pip_lines(text, "rag.ipynb", needs)
    assert again == text and more == []


def test_pip_line_with_shell_operators_is_reported_not_edited():
    nb = {"cells": [{"cell_type": "code", "source": ["!pip install langchain && echo done"], "metadata": {}, "outputs": []}]}
    text = json.dumps(nb)
    new, findings = update_pip_lines(text, "x.ipynb", Needs(classic=True))
    assert new == text
    assert findings[0].code == "LCM013" and not findings[0].fixable


def test_mask_round_trip_with_continuation_and_indent():
    code = "if True:\n    %pip install a \\\n        b\n    x = 1\n!ls\ndf?\n"
    masked, saved = mask_magics(code)
    assert "%pip" not in masked and "!ls" not in masked
    assert unmask_magics(masked, saved) == code


def test_not_a_notebook_is_reported(table):
    result = process_notebook("{ nope", "bad.ipynb", table, "classic")
    assert [f.code for f in result.findings] == ["LCM011"]
