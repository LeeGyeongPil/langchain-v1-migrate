"""Names that still work through langchain-classic but are not the v1 way.

These are only reported (never rewritten). Sources:
https://docs.langchain.com/oss/python/migrate/langchain-v1 (checked 2026-11-18)
"""

from __future__ import annotations

#: names (as imported from langchain / langchain_classic) reported as LCM009
LEGACY_NAMES = frozenset(
    {
        "LLMChain",
        "ConversationChain",
        "RetrievalQA",
        "ConversationalRetrievalChain",
        "initialize_agent",
        "AgentExecutor",
    }
)

MIGRATION_GUIDE_URL = "https://docs.langchain.com/oss/python/migrate/langchain-v1"


def is_hub(module: str, name: str) -> bool:
    """True for ``langchain(.|_classic.)hub`` imports (hub is deprecated in classic)."""
    if module in ("langchain.hub", "langchain_classic.hub") or module.startswith(("langchain.hub.", "langchain_classic.hub.")):
        return True
    return module in ("langchain", "langchain_classic") and name == "hub"
