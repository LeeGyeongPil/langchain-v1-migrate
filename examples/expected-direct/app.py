"""A small RAG helper written against LangChain 0.3."""
import os
from typing import Optional

from langchain_classic.chains import RetrievalQA, LLMChain  # keep this comment
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.memory import (
    ConversationBufferMemory,  # chat history
    ConversationSummaryMemory,
)
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.documents import Document
from langchain_classic.storage import LocalFileStore
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain.chat_models import init_chat_model
from langchain_classic import hub
import langchain_classic.chains.retrieval as retrieval_module
from langchain_core.messages import HumanMessage

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # older installs
    RecursiveCharacterTextSplitter = None


def build_chain(llm, retriever, store_dir: Optional[str] = None):
    """Wire a retriever and a prompt into a QA chain."""
    prompt = PromptTemplate.from_template("Answer using {context}: {question}")
    memory = ConversationBufferMemory(memory_key="history")
    chain = LLMChain(llm=llm, prompt=prompt)
    qa = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)
    return chain, qa, memory


def main() -> None:
    from langchain_classic.agents import initialize_agent  # lazy import inside a function

    print(os.getcwd(), HumanMessage(content="hi"), Document(page_content="x"))
    print(initialize_agent, hub, retrieval_module)


if __name__ == "__main__":
    main()
