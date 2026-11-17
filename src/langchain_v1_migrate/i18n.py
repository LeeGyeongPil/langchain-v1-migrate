"""Language selection and message lookup (English / Korean).

Order: ``--lang`` > ``LANGCHAIN_V1_MIGRATE_LANG`` > ``LC_ALL`` / ``LC_MESSAGES`` / ``LANG``.
Anything that does not start with ``ko`` is English.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import resources

LANGUAGES = ("en", "ko")
ENV_VAR = "LANGCHAIN_V1_MIGRATE_LANG"

_current = "en"


def _normalize(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if value in ("c", "posix"):
        return "en"
    return "ko" if value.startswith("ko") else "en"


def resolve_lang(cli_value: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Pick ``en`` or ``ko`` using the documented precedence."""
    env = os.environ if env is None else env
    for candidate in (cli_value, env.get(ENV_VAR), env.get("LC_ALL"), env.get("LC_MESSAGES"), env.get("LANG")):
        picked = _normalize(candidate)
        if picked:
            return picked
    return "en"


def lang_from_argv(argv: Sequence[str]) -> str | None:
    """Find ``--lang X`` / ``--lang=X`` before argparse runs (so ``--help`` is localised)."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


@lru_cache(maxsize=None)
def messages(lang: str) -> dict[str, str]:
    path = resources.files("langchain_v1_migrate.messages").joinpath(f"{lang}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def set_lang(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def current_lang() -> str:
    return _current


def t(key: str, **values: object) -> str:
    """Look up a message in the current language and fill ``{placeholders}``."""
    table = messages(_current)
    template = table.get(key)
    if template is None:  # fall back to English rather than crash on a missing key
        template = messages("en")[key]
    return template.format(**values) if values else template
