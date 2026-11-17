"""AC-7: CLI flow, exit codes and JSON output."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from langchain_v1_migrate.cli import main

from conftest import EXAMPLES, read_tree

KEYS = {"code", "severity", "fixable", "path", "line", "col", "message", "old", "new"}


def test_exit_codes(capsys, tmp_path: Path):
    assert main(["check", str(EXAMPLES / "legacy")]) == 1
    out = capsys.readouterr().out
    assert "LCM002" in out and "fixable" in out and "Summary:" in out

    assert main(["check", str(EXAMPLES / "clean")]) == 0
    assert "Nothing to migrate" in capsys.readouterr().out

    assert main(["check", str(tmp_path / "missing")]) == 2
    assert "does not exist" in capsys.readouterr().err

    assert main([]) == 2  # no command: help + usage error code
    assert main(["lookup", "not.a.module.Name"]) == 2
    assert main(["check", "--table", str(tmp_path / "nope.json"), str(EXAMPLES / "clean")]) == 2


def test_fix_preview_does_not_write(capsys):
    before = read_tree(EXAMPLES / "legacy")
    code = main(["fix", str(EXAMPLES / "legacy")])
    cap = capsys.readouterr()
    assert read_tree(EXAMPLES / "legacy") == before
    assert code == 1  # mixed.py still has errors a human must fix
    assert "--- a/" in cap.out and "+from langchain_classic.agents import AgentExecutor" in cap.out
    assert "Preview only" in cap.err and "LCM004" in cap.err


def test_fix_write_then_check_clean(capsys, tmp_path: Path):
    work = tmp_path / "proj"
    shutil.copytree(EXAMPLES / "legacy", work)
    (work / "mixed.py").unlink()
    assert main(["fix", str(work), "--write"]) == 0
    assert "Wrote 5 file(s)" in capsys.readouterr().out
    assert main(["check", str(work)]) == 0
    assert main(["check", str(work), "--strict"]) == 1  # hub is deprecated -> warning
    capsys.readouterr()
    # a second fix has nothing left to do
    assert main(["fix", str(work), "--write"]) == 0
    assert "Wrote 0 file(s)" in capsys.readouterr().out


def test_no_deps_flag(capsys, tmp_path: Path):
    work = tmp_path / "proj"
    shutil.copytree(EXAMPLES / "legacy", work)
    assert main(["fix", str(work), "--write", "--no-deps"]) == 1
    assert "langchain-classic" not in (work / "requirements.txt").read_text()
    assert "langchain_classic" in (work / "app.py").read_text()


def test_json_schema(capsys):
    assert main(["check", str(EXAMPLES / "legacy"), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == 1
    assert data["table"]["from"] == {"langchain": "0.3.29"}
    assert data["table"]["to"]["langchain-classic"] == "1.0.8"
    assert data["findings"] and all(KEYS <= set(f) for f in data["findings"])
    summary = data["summary"]
    assert set(summary) == {"files", "fixable", "errors", "warnings", "info"}
    assert summary["errors"] == sum(1 for f in data["findings"] if f["severity"] == "error")
    assert summary["fixable"] == sum(1 for f in data["findings"] if f["fixable"])
    assert {f["code"] for f in data["findings"]} >= {"LCM001", "LCM002", "LCM003", "LCM004", "LCM005", "LCM006", "LCM007", "LCM008", "LCM009", "LCM010", "LCM013"}


def test_lookup(capsys):
    assert main(["lookup", "langchain.prompts.PipelinePromptTemplate"]) == 1
    assert "does not exist" in capsys.readouterr().out

    assert main(["lookup", "langchain.chat_models.ChatAnthropic", "--target", "direct"]) == 0
    out = capsys.readouterr().out
    assert "* direct   langchain_community.chat_models.ChatAnthropic" in out
    assert "  classic  langchain_classic.chat_models.ChatAnthropic" in out

    assert main(["lookup", "langchain.chat_models.ChatAnthropic"]) == 0
    out = capsys.readouterr().out
    assert "langchain-community" in out and "re-exports" in out

    assert main(["lookup", "langchain.indexes.index"]) == 0
    assert "sqlalchemy[asyncio]" in capsys.readouterr().out

    assert main(["lookup", "langchain.agents.create_agent"]) == 0
    assert "unchanged" in capsys.readouterr().out

    assert main(["lookup", "langchain.pydantic_v1"]) == 1


def test_table_command(capsys, tmp_path: Path):
    sites = Path(__file__).parent / "fixtures" / "sites"
    out_file = tmp_path / "mine.json"
    code = main(["table", "--from-site", str(sites / "old"), "--to-site", str(sites / "new"), "-o", str(out_file)])
    assert code == 0 and out_file.exists()
    # the freshly computed table can be used by check
    assert main(["check", str(EXAMPLES / "clean"), "--table", str(out_file)]) == 0
    capsys.readouterr()
    assert main(["table", "--from-site", str(tmp_path), "--to-site", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().err


def test_exclude_and_default_excludes(capsys, tmp_path: Path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "a.py").write_text("from langchain.chains import LLMChain\n")
    (tmp_path / "skip.py").write_text("from langchain.chains import LLMChain\n")
    (tmp_path / "keep.py").write_text("from langchain.chains import LLMChain\n")
    assert main(["check", str(tmp_path), "--exclude", "skip.py", "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert {Path(f["path"]).name for f in data["findings"]} == {"keep.py"}


def test_ci_pipefail_step_uses_bash_shell():
    """Q-1: the 'if ... | tee' step needs a shell with pipefail (GitHub's `shell: bash`)."""
    from pathlib import Path

    ci = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    step = ci.split("original file fails the way users see it", 1)[1]
    assert "| tee" not in step or "shell: bash" in step.split("run:", 1)[0]
