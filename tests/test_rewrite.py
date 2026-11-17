"""AC-2 and AC-3: byte-preserving, idempotent, name-aware import rewriting."""

from __future__ import annotations

import ast

from langchain_v1_migrate.rewrite import rewrite_source

from conftest import EXAMPLES


def _rewrite(source: str, table, target: str = "classic"):
    return rewrite_source(source, "t.py", table, target)


def _codes(result) -> list[str]:
    return [f.code for f in result.findings]


def test_app_golden(table):
    source = (EXAMPLES / "legacy" / "app.py").read_text(encoding="utf-8")
    expected = (EXAMPLES / "expected" / "app.py").read_bytes()
    result = _rewrite(source, table)
    assert result.source.encode("utf-8") == expected
    # comments, a parenthesised multi-line import and a try/except import survive
    assert "# keep this comment" in result.source
    assert "    ConversationBufferMemory,  # chat history\n" in result.source
    assert "except ImportError:  # older installs" in result.source


def test_idempotent(table):
    for name in ("app.py", "mixed.py", "community.py"):
        source = (EXAMPLES / "legacy" / name).read_text(encoding="utf-8")
        once = _rewrite(source, table).source
        twice = _rewrite(once, table)
        assert twice.source == once, name


def test_untouched_lines_identical(table):
    source = (EXAMPLES / "legacy" / "app.py").read_text(encoding="utf-8")
    result = _rewrite(source, table).source
    before = [line for line in source.splitlines(keepends=True) if "langchain" not in line]
    after = [line for line in result.splitlines(keepends=True) if "langchain" not in line]
    assert before == after


def test_crlf_and_bom_preserved(table):
    source = "﻿from langchain.retrievers import EnsembleRetriever\r\nx = 1\r\n"
    result = _rewrite(source, table)
    assert result.source == "﻿from langchain_classic.retrievers import EnsembleRetriever\r\nx = 1\r\n"


def test_mixed_split(table):
    result = _rewrite("from langchain.agents import create_agent, AgentExecutor  # note\n", table)
    assert result.source == (
        "from langchain.agents import create_agent  # note\n"
        "from langchain_classic.agents import AgentExecutor\n"
    )
    assert "LCM002" in _codes(result)
    assert "LCM001" not in _codes(result)


def test_split_inside_block_and_semicolon_line(table):
    src = "def f():\n    from langchain.agents import create_agent, AgentExecutor\n    return 1\n"
    out = _rewrite(src, table).source
    assert out == (
        "def f():\n    from langchain.agents import create_agent\n"
        "    from langchain_classic.agents import AgentExecutor\n    return 1\n"
    )
    inline = "import os; from langchain.agents import create_agent, AgentExecutor\n"
    assert _rewrite(inline, table).source == (
        "import os; from langchain.agents import create_agent; from langchain_classic.agents import AgentExecutor\n"
    )


def test_aliases_are_kept(table):
    result = _rewrite("from langchain.agents import AgentExecutor as AE, create_agent as ca\n", table)
    assert result.source == (
        "from langchain_classic.agents import AgentExecutor as AE\nfrom langchain.agents import create_agent as ca\n"
    )


def test_gone_name_and_module_reported(table):
    src = (
        "from langchain.prompts import PipelinePromptTemplate\n"
        "from langchain.pydantic_v1 import BaseModel\n"
    )
    result = _rewrite(src, table)
    assert result.source == src  # nothing is guessed
    assert _codes(result) == ["LCM003", "LCM004"]
    assert [f.line for f in result.findings] == [1, 2]
    assert all(f.severity == "error" for f in result.findings)


def test_gone_name_next_to_movable_name(table):
    result = _rewrite("from langchain.prompts import PromptTemplate, PipelinePromptTemplate\n", table)
    assert result.source == (
        "from langchain_classic.prompts import PromptTemplate\nfrom langchain.prompts import PipelinePromptTemplate\n"
    )
    assert set(_codes(result)) == {"LCM002", "LCM003"}


def test_bare_import_reported(table):
    src = "import langchain.chains\nimport langchain.chains as chains\n"
    result = _rewrite(src, table)
    assert result.source == "import langchain.chains\nimport langchain_classic.chains as chains\n"
    assert _codes(result) == ["LCM005", "LCM001"]


def test_star_import(table):
    moved = _rewrite("from langchain.chains import *\n", table)
    assert moved.source == "from langchain_classic.chains import *\n"
    split = _rewrite("from langchain.agents import *\n", table)
    assert split.source == "from langchain.agents import *\n"
    assert _codes(split) == ["LCM005"]


def test_hub_moved_and_warned(table):
    result = _rewrite("from langchain import hub\nfrom langchain.hub import pull\n", table)
    assert result.source == "from langchain_classic import hub\nfrom langchain_classic.hub import pull\n"
    codes = _codes(result)
    assert codes.count("LCM008") == 2
    assert "deprecated" in next(f.message for f in result.findings if f.code == "LCM008")


def test_new_style_imports_untouched(table):
    src = (
        "from langchain.agents import create_agent\nfrom langchain.agents.middleware import X\n"
        "from langchain.chat_models import init_chat_model\nfrom langchain_core.prompts import PromptTemplate\n"
        "import langchain\nfrom . import langchain_helpers\nimport langchain_openai\n"
    )
    result = _rewrite(src, table)
    assert result.source == src
    assert result.findings == []


def test_parse_error_becomes_finding(table):
    result = _rewrite("from langchain.chains import (\n", table)
    assert _codes(result) == ["LCM011"]
    assert result.source == "from langchain.chains import (\n"


def test_legacy_names_and_react_agent_reported(table):
    src = "from langgraph.prebuilt import create_react_agent\nfrom langchain_classic.chains import LLMChain\n"
    result = _rewrite(src, table)
    assert result.source == src
    assert _codes(result) == ["LCM009", "LCM009"]
    assert result.needs.classic


def test_all_targets_exist_in_new_index(table):
    """Every (module, name) the golden files import must exist in 1.x or classic."""
    checked = 0
    for folder in ("expected", "expected-direct"):
        for py in sorted((EXAMPLES / folder).glob("*.py")):
            if py.name == "mixed.py":  # deliberately keeps unfixable lines
                continue
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in ("langchain", "langchain_classic"):
                    for alias in node.names:
                        assert table.exists_in_new(node.module, alias.name), f"{py.name}: {node.module}.{alias.name}"
                        checked += 1
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in ("langchain", "langchain_classic"):
                            assert table.exists_in_new(alias.name), f"{py.name}: {alias.name}"
                            checked += 1
    assert checked >= 15
