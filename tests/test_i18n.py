"""AC-8: English / Korean output."""

from __future__ import annotations

import json
import re

import pytest

from langchain_v1_migrate import i18n
from langchain_v1_migrate.cli import main
from langchain_v1_migrate.findings import CODES

from conftest import EXAMPLES

HANGUL = re.compile(r"[가-힣]")


def test_lang_flag(capsys):
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "--help"])
    ko_help = capsys.readouterr().out
    assert HANGUL.search(ko_help)

    with pytest.raises(SystemExit):
        main(["--lang", "en", "--help"])
    en_help = capsys.readouterr().out
    assert not HANGUL.search(en_help) and "Exit codes" in en_help

    main(["--lang", "ko", "check", str(EXAMPLES / "legacy")])
    assert "수정가능" in capsys.readouterr().out
    main(["check", str(EXAMPLES / "legacy"), "--lang", "en"])  # flag after the command works too
    out = capsys.readouterr().out
    assert "fixable" in out and not HANGUL.search(out)


def test_env_precedence(monkeypatch):
    env = {"LANG": "ko_KR.UTF-8"}
    assert i18n.resolve_lang(None, env) == "ko"
    assert i18n.resolve_lang(None, {"LANG": "en_US.UTF-8"}) == "en"
    assert i18n.resolve_lang(None, {"LANG": "de_DE.UTF-8"}) == "en"
    assert i18n.resolve_lang(None, {}) == "en"
    # LC_ALL beats LC_MESSAGES beats LANG
    assert i18n.resolve_lang(None, {"LC_ALL": "en_US", "LC_MESSAGES": "ko_KR", "LANG": "ko_KR"}) == "en"
    assert i18n.resolve_lang(None, {"LC_MESSAGES": "ko_KR", "LANG": "en_US"}) == "ko"
    # tool variable beats the locale, --lang beats the tool variable
    assert i18n.resolve_lang(None, {"LANGCHAIN_V1_MIGRATE_LANG": "en", "LANG": "ko_KR"}) == "en"
    assert i18n.resolve_lang("ko", {"LANGCHAIN_V1_MIGRATE_LANG": "en"}) == "ko"
    assert i18n.lang_from_argv(["check", "--lang=ko"]) == "ko"
    assert i18n.lang_from_argv(["check", "--lang", "en"]) == "en"
    assert i18n.lang_from_argv(["check"]) is None


def test_env_reaches_the_cli(monkeypatch, capsys):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    main(["check", str(EXAMPLES / "clean")])
    assert "옮길 것이 없습니다" in capsys.readouterr().out
    monkeypatch.setenv("LANGCHAIN_V1_MIGRATE_LANG", "en")
    main(["check", str(EXAMPLES / "clean")])
    assert "Nothing to migrate" in capsys.readouterr().out
    main(["--lang", "ko", "check", str(EXAMPLES / "clean")])
    assert "옮길 것이 없습니다" in capsys.readouterr().out


def test_message_keys_match():
    en, ko = i18n.messages("en"), i18n.messages("ko")
    assert set(en) == set(ko)
    assert all(en[k].strip() and ko[k].strip() for k in en)
    # same placeholders in both languages
    for key in en:
        assert sorted(re.findall(r"\{(\w+)\}", en[key])) == sorted(re.findall(r"\{(\w+)\}", ko[key])), key
    # every finding code has a message
    for code in CODES:
        assert any(k == f"msg.{code}" or k.startswith(f"msg.{code}.") for k in en), code


def test_json_codes_language_independent(capsys):
    main(["check", str(EXAMPLES / "legacy"), "--format", "json", "--lang", "en"])
    en = json.loads(capsys.readouterr().out)
    main(["check", str(EXAMPLES / "legacy"), "--format", "json", "--lang", "ko"])
    ko = json.loads(capsys.readouterr().out)
    key = lambda f: (f["code"], f["severity"], f["fixable"], f["path"], f["line"], f["col"], f["cell"], f["old"], f["new"])
    assert [key(f) for f in en["findings"]] == [key(f) for f in ko["findings"]]
    assert en["summary"] == ko["summary"]
    assert [f["message"] for f in en["findings"]] != [f["message"] for f in ko["findings"]]
    assert list(en) == list(ko)


# --- round 2 regressions -------------------------------------------------------------------

def test_ko_text_has_no_english_severity_words(capsys):
    """Q-2: the severity column is translated and the message column lines up."""
    main(["--lang", "ko", "check", str(EXAMPLES / "legacy")])
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if re.match(r"\s+(cell\d+:)?\d+:\d+ +LCM", ln)]
    assert rows
    for ln in rows:
        assert not re.search(r" (error|warning|info) ", ln), ln
    from langchain_v1_migrate.report import _width

    # message starts at the same display column on every row
    cols = set()
    for ln in rows:
        head = re.match(r"(\s+\S+ +LCM\d+  \S+ *)", ln).group(1)
        cols.add(_width(head))
    assert len(cols) == 1, cols


def test_ko_help_is_translated(capsys):
    for argv in (["--lang", "ko", "--help"], ["--lang", "ko", "check", "--help"]):
        with pytest.raises(SystemExit):
            main(argv)
        out = capsys.readouterr().out
        for english in ("usage:", "options:", "positional arguments", "show this help message"):
            assert english not in out, (argv, english)
        assert "사용법:" in out and "옵션" in out
    with pytest.raises(SystemExit):
        main(["--lang", "en", "--help"])
    assert "usage:" in capsys.readouterr().out


def test_severity_keys_exist_in_both_languages():
    for lang in i18n.LANGUAGES:
        for sev in ("error", "warning", "info"):
            assert f"report.severity.{sev}" in i18n.messages(lang)
