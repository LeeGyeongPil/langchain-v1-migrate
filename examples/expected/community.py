"""Names that classic only re-exports from langchain-community or langchain-core."""
from langchain_classic.chat_models import FakeListChatModel
from langchain.chat_models import init_chat_model
from langchain_classic.vectorstores import FAISS
from langchain_classic.indexes import SQLRecordManager, index
from langchain_classic.text_splitter import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain_classic.prompts import PromptTemplate


def make(embeddings):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500)
    llm = FakeListChatModel(responses=["hi"])
    return FAISS, SQLRecordManager, index, splitter, llm, init_chat_model, PromptTemplate, TokenTextSplitter
