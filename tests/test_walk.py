"""Folder walking skips virtual environments and installed packages."""

from __future__ import annotations

from pathlib import Path

from langchain_v1_migrate.walk import collect

OLD = "from langchain.chains import LLMChain\n"


def _make_project(root: Path) -> Path:
    (root / "app.py").write_text(OLD)
    env = root / "myenv"
    pkg = env / "lib" / "python3.12" / "site-packages" / "someplugin"
    pkg.mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (pkg / "__init__.py").write_text(OLD)
    return pkg / "__init__.py"


def test_custom_named_venv_is_skipped(tmp_path: Path) -> None:
    installed = _make_project(tmp_path)
    names = {p.resolve() for p in collect([str(tmp_path)]).python}
    assert (tmp_path / "app.py").resolve() in names
    assert installed.resolve() not in names


def test_site_packages_without_pyvenv_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(OLD)
    sp = tmp_path / "lib" / "site-packages" / "x"
    sp.mkdir(parents=True)
    (sp / "m.py").write_text(OLD)
    names = {p.resolve() for p in collect([str(tmp_path)]).python}
    assert names == {(tmp_path / "app.py").resolve()}


def test_explicit_file_and_root_env_are_still_used(tmp_path: Path) -> None:
    installed = _make_project(tmp_path)
    assert collect([str(installed)]).python == [installed]
    # A folder given as the root is walked itself; its site-packages is still skipped.
    (tmp_path / "myenv" / "tool.py").write_text(OLD)
    walked = collect([str(tmp_path / "myenv")]).python
    assert walked == [tmp_path / "myenv" / "tool.py"]
