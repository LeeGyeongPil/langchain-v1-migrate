# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-11-19

### Security
- Bumped `python-dotenv` from 1.0.1 to 1.2.2 in the sample `requirements.txt` files under `examples/` (GHSA-mf9w-mj56-hr94). The tool itself does not depend on it.

## [0.1.1] - 2026-11-18

### Fixed
- Folder walks now skip virtual environments of any name (folders with `pyvenv.cfg`) and `site-packages`/`dist-packages`, so installed packages are no longer checked or rewritten by `fix . --write`.

## [0.1.0] - 2026-11-18

### Added
- `check`, `fix`, `lookup` and `table` commands.
- Bundled move table computed from langchain 0.3.29, langchain 1.5.0, langchain-classic 1.0.8 and langchain-community 0.4.2 (1,313 modules moved, 7 partly kept with 300 names moved, 9 gone).
- Name-level rewriting with LibCST: import splitting, aliases, `try/except` blocks, star and bare imports reported.
- `--target classic|direct`: follow langchain-classic re-export shims to the package that defines the name.
- `.ipynb` support that keeps IPython magics and the notebook layout.
- Dependency updates for `requirements*.txt`, `pyproject.toml` (PEP 621 and Poetry) and notebook `%pip` lines.
- English and Korean output (`--lang`, `LANGCHAIN_V1_MIGRATE_LANG`, locale variables), JSON output and CI exit codes.
- Korean output with translated severity labels, width-aligned columns and a translated `--help`.
