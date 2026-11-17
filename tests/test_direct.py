"""AC-4: re-export shims and extra dependencies, `--target classic|direct`."""

from __future__ import annotations

from pathlib import Path

from langchain_v1_migrate.rewrite import rewrite_source

from conftest import EXAMPLES, migrate_tree, read_tree


def test_classic_target_flags_shims(table):
    source = (EXAMPLES / "legacy" / "community.py").read_text(encoding="utf-8")
    result = rewrite_source(source, "community.py", table, "classic")

    out = result.source
    assert "from langchain_classic.chat_models import FakeListChatModel\n" in out
    assert "from langchain.chat_models import init_chat_model\n" in out  # stays in 1.x
    assert "from langchain_classic.vectorstores import FAISS\n" in out

    shim_lines = [f.line for f in result.findings if f.code == "LCM006"]
    assert shim_lines == [2, 3]  # FakeListChatModel, FAISS
    sql = [f for f in result.findings if f.code == "LCM007"]
    assert len(sql) == 1 and sql[0].line == 4  # SQLRecordManager / index
    assert "sqlalchemy[asyncio]" in sql[0].message
    assert result.needs.classic and result.needs.community_extra and result.needs.sqlalchemy
    assert not result.needs.community_direct


def test_direct_target_follows_shims(table):
    src = (
        "from langchain.chat_models import FakeListChatModel\n"
        "from langchain.text_splitter import RecursiveCharacterTextSplitter\n"
        "from langchain.prompts import PromptTemplate\n"
    )
    result = rewrite_source(src, "t.py", table, "direct")
    assert result.source == (
        "from langchain_community.chat_models import FakeListChatModel\n"
        "from langchain_text_splitters import RecursiveCharacterTextSplitter\n"
        "from langchain_core.prompts import PromptTemplate\n"
    )
    assert result.needs.community_direct and result.needs.text_splitters
    assert not result.needs.classic
    assert not any(f.code == "LCM006" for f in result.findings)


def test_direct_target_splits_by_origin(table):
    result = rewrite_source("from langchain.chains import LLMChain, OpenAPIEndpointChain\n", "t.py", table, "direct")
    assert result.source == (
        "from langchain_classic.chains import LLMChain\n"
        "from langchain_community.chains.openapi.chain import OpenAPIEndpointChain\n"
    )


def test_direct_target_golden(table, tmp_path: Path):
    out = tmp_path / "tree"
    migrate_tree(EXAMPLES / "legacy", out, table, target="direct")
    assert read_tree(out) == read_tree(EXAMPLES / "expected-direct")


def test_classic_target_golden_tree(table, tmp_path: Path):
    out = tmp_path / "tree"
    migrate_tree(EXAMPLES / "legacy", out, table, target="classic")
    assert read_tree(out) == read_tree(EXAMPLES / "expected")


def test_dead_reexport_is_warned_not_hidden(table):
    """ChatAnthropic is listed by classic but langchain-community 0.4.2 no longer defines it."""
    for target in ("classic", "direct"):
        result = rewrite_source("from langchain.chat_models import ChatAnthropic\n", "t.py", table, target)
        assert [f.code for f in result.findings] == ["LCM001", "LCM006"]
        assert "no longer defines" in result.findings[1].message
    # a live shim name gets the ordinary shim warning instead
    live = rewrite_source("from langchain.vectorstores import FAISS\n", "t.py", table, "classic")
    assert "no longer defines" not in " ".join(f.message for f in live.findings)
