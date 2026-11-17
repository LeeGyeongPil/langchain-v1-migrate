"""Names that classic only re-exports from langchain-community or langchain-core."""
from langchain.chat_models import FakeListChatModel, init_chat_model
from langchain.vectorstores import FAISS
from langchain.indexes import SQLRecordManager, index
from langchain.text_splitter import RecursiveCharacterTextSplitter, TokenTextSplitter
from langchain.prompts import PromptTemplate


def make(embeddings):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500)
    llm = FakeListChatModel(responses=["hi"])
    return FAISS, SQLRecordManager, index, splitter, llm, init_chat_model, PromptTemplate, TokenTextSplitter
