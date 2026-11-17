"""AC-6: dependency files."""

from __future__ import annotations

import tomlkit

from langchain_v1_migrate import deps
from langchain_v1_migrate.rewrite import Needs

CLASSIC = Needs(classic=True)
COMMUNITY = Needs(classic=True, community_extra=True)
ALL = Needs(classic=True, community_extra=True, sqlalchemy=True)


def test_requirements_added():
    text = "# runtime\nlangchain>=1.0\nlangchain-openai\n"
    new, findings = deps.update_requirements(text, "requirements.txt", CLASSIC)
    assert new == text + "langchain-classic>=1.0,<2\n"
    assert [f.code for f in findings] == ["LCM013"] and findings[0].line == 4
    # missing final newline and CRLF files are handled
    assert deps.update_requirements("a", "r.txt", CLASSIC)[0] == "a\nlangchain-classic>=1.0,<2\n"
    assert deps.update_requirements("a\r\n", "r.txt", CLASSIC)[0] == "a\r\nlangchain-classic>=1.0,<2\r\n"


def test_pyproject_pep621_and_poetry():
    pep621 = (
        '[project]\nname = "x"\nrequires-python = ">=3.11"\ndependencies = [\n'
        '    "langchain>=1.0",  # keep\n    "httpx",\n]\n\n[tool.ruff]\nline-length = 100\n'
    )
    new, _ = deps.update_pyproject(pep621, "pyproject.toml", CLASSIC)
    assert new == pep621.replace('    "httpx",\n', '    "httpx",\n    "langchain-classic>=1.0,<2",\n')
    assert tomlkit.parse(new)["project"]["dependencies"][-1] == "langchain-classic>=1.0,<2"

    poetry = '[tool.poetry.dependencies]\npython = "^3.11"\nlangchain = "^1.0"  # app\n'
    new, _ = deps.update_pyproject(poetry, "pyproject.toml", CLASSIC)
    assert new == poetry + 'langchain-classic = ">=1.0,<2"\n'

    neither = '[tool.ruff]\nline-length = 100\n'
    assert deps.update_pyproject(neither, "pyproject.toml", CLASSIC) == (neither, [])


def test_community_extra_and_sqlalchemy():
    new, _ = deps.update_requirements("langchain\n", "r.txt", ALL)
    assert new == "langchain\nlangchain-classic[community]>=1.0,<2\nsqlalchemy[asyncio]\n"

    direct = Needs(community_direct=True, text_splitters=True)
    new, _ = deps.update_requirements("langchain\n", "r.txt", direct)
    assert new == "langchain\nlangchain-community>=0.4\nlangchain-text-splitters>=1.1,<2\n"

    poetry = '[tool.poetry.dependencies]\npython = "^3.11"\n'
    new, _ = deps.update_pyproject(poetry, "pyproject.toml", ALL)
    parsed = tomlkit.parse(new)["tool"]["poetry"]["dependencies"]
    assert parsed["langchain-classic"]["extras"] == ["community"]
    assert parsed["sqlalchemy"]["extras"] == ["asyncio"]

    # classic already listed without the extra: community is added next to it
    new, _ = deps.update_requirements("langchain-classic>=1.0\n", "r.txt", COMMUNITY)
    assert new == "langchain-classic>=1.0\nlangchain-community>=0.4\n"


def test_idempotent_and_old_pin_warning():
    text = "langchain==0.3.29\nsqlalchemy[asyncio]\n"
    once, findings = deps.update_requirements(text, "requirements.txt", ALL)
    codes = [f.code for f in findings]
    assert codes[0] == "LCM012" and "langchain==0.3.29" in findings[0].message
    assert once.startswith("langchain==0.3.29\n")  # the pin itself is not touched
    twice, again = deps.update_requirements(once, "requirements.txt", ALL)
    assert twice == once
    assert [f.code for f in again] == ["LCM012"]

    py = '[project]\nname = "x"\ndependencies = ["langchain>=1.0"]\n'
    first, _ = deps.update_pyproject(py, "pyproject.toml", CLASSIC)
    second, found = deps.update_pyproject(first, "pyproject.toml", CLASSIC)
    assert second == first and found == []


def test_nothing_needed_means_no_change():
    text = "langchain>=1.0\n"
    assert deps.update_requirements(text, "r.txt", Needs()) == (text, [])


def test_hash_pinned_file_is_not_edited():
    text = "langchain==1.0.0 --hash=sha256:abc\n"
    new, findings = deps.update_requirements(text, "r.txt", CLASSIC)
    assert new == text
    assert findings[-1].code == "LCM013" and not findings[-1].fixable


def test_old_python_floor_warns():
    py = '[project]\nname = "x"\nrequires-python = ">=3.9"\ndependencies = ["langchain-classic>=1.0"]\n'
    _, findings = deps.update_pyproject(py, "pyproject.toml", Needs(classic=True))
    assert [f.code for f in findings] == ["LCM012"]
    assert "3.10" in findings[0].message
