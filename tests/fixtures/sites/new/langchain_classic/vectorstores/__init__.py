from langchain_classic._api import create_importer

DEPRECATED_LOOKUP = {"FAISS": "langchain_community.vectorstores"}

_import_attribute = create_importer(__package__, deprecated_lookups=DEPRECATED_LOOKUP)


def __getattr__(name):
    return _import_attribute(name)


__all__ = ["FAISS", "VectorStore"]
