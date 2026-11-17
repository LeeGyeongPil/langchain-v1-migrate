from langchain_classic.chat_models.base import init_chat_model


def __getattr__(name):
    from langchain_community import chat_models

    return getattr(chat_models, name)


__all__ = ["ChatAnthropic", "init_chat_model"]
