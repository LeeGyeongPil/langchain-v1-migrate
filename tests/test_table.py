"""AC-1: the move table is computed from installed package trees."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from langchain_v1_migrate.table import compute

from conftest import FIXTURES

OLD = FIXTURES / "sites" / "old"
NEW = FIXTURES / "sites" / "new"


def test_bundled_table_counts(table):
    assert table.meta["from"] == {"langchain": "0.3.29"}
    assert table.meta["to"] == {"langchain": "1.5.0", "langchain-classic": "1.0.8", "langchain-community": "0.4.2"}
    assert table.counts["move"] == 1313
    assert table.counts["partial"] == 7
    assert table.counts["gone"] == 9
    assert table.counts["partial_names_moved"] == 300


def test_compute_from_fixture_sites():
    data = compute.build_table(OLD, NEW, computed_on="2026-11-18")
    assert compute.dumps(data, pretty=True) == (FIXTURES / "expected_table.json").read_bytes()

    # partial module: create_agent stays, AgentExecutor moved
    assert data["old"]["langchain.agents"] == "partial"
    assert data["new"]["langchain.agents"] == ["create_agent"]
    assert data["classic"]["langchain_classic.agents"] == ["AgentExecutor"]
    # gone modules
    assert data["old"]["langchain.prompts.pipeline"] == "gone"
    assert data["old"]["langchain.pydantic_v1"] == "gone"
    # three re-export shapes
    origins = data["origins"]
    assert origins["langchain_classic.prompts"]["PromptTemplate"] == ["langchain_core.prompts", "PromptTemplate"]
    assert origins["langchain_classic.vectorstores"]["FAISS"] == ["langchain_community.vectorstores", "FAISS"]
    assert origins["langchain_classic.chat_models"]["ChatAnthropic"] == ["langchain_community.chat_models", "ChatAnthropic"]
    assert "init_chat_model" not in origins["langchain_classic.chat_models"]
    # sqlalchemy[asyncio] flag follows the import chain
    assert data["extras"]["langchain_classic.indexes"] == ["sqlalchemy_asyncio"]
    assert "langchain_classic.chains" not in data["extras"]


def test_compute_is_deterministic(tmp_path: Path):
    first = tmp_path / "a.json.gz"
    second = tmp_path / "b.json.gz"
    compute.write_table(compute.build_table(OLD, NEW, "2026-11-18"), first)
    compute.write_table(compute.build_table(OLD, NEW, "2026-11-18"), second)
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()).startswith(b"{")


def test_missing_package_gives_actionable_error(tmp_path: Path):
    with pytest.raises(compute.TableError, match="not found"):
        compute.build_table(tmp_path, NEW)


def test_table_file_round_trip(tmp_path: Path):
    from langchain_v1_migrate.table import load

    path = tmp_path / "t.json"
    compute.write_table(compute.build_table(OLD, NEW), path)
    loaded = load.from_file(path)
    res = loaded.resolve("langchain.agents", "AgentExecutor")
    assert (res.status, res.module) == ("move", "langchain_classic.agents")
    assert loaded.resolve("langchain.agents", "create_agent").status == "keep"
    assert loaded.resolve("langchain.prompts", "PipelinePromptTemplate").status == "gone-name"


def test_dead_reexports_need_a_community_tree(tmp_path: Path):
    community = tmp_path / "community"
    (community / "langchain_community" / "chat_models").mkdir(parents=True)
    (community / "langchain_community" / "chat_models" / "__init__.py").write_text("__all__ = []\n")
    (community / "langchain_community" / "vectorstores").mkdir(parents=True)
    (community / "langchain_community" / "vectorstores" / "__init__.py").write_text("class FAISS: ...\n")
    (community / "langchain_community-0.4.2.dist-info").mkdir()
    (community / "langchain_community-0.4.2.dist-info" / "METADATA").write_text("Name: langchain-community\n")
    data = compute.build_table(OLD, NEW, community_site=community)
    assert data["dead"] == {"langchain_classic.chat_models": ["ChatAnthropic"]}
    assert data["meta"]["to"]["langchain-community"] == "0.4.2"
    assert compute.build_table(OLD, NEW)["dead"] == {}
