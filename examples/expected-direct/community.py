"""Names that classic only re-exports from langchain-community or langchain-core."""
from langchain_community.chat_models import FakeListChatModel
from langchain.chat_models import init_chat_model
from langchain_community.vectorstores import FAISS
from langchain_classic.indexes import SQLRecordManager
from langchain_core.indexing.api import index
from langchain_text_splitters import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain_core.prompts import PromptTemplate


def make(embeddings):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500)
    llm = FakeListChatModel(responses=["hi"])
    return FAISS, SQLRecordManager, index, splitter, llm, init_chat_model, PromptTemplate, TokenTextSplitter
