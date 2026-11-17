"""A small RAG helper written against LangChain 0.3."""
import os
from typing import Optional

from langchain.chains import RetrievalQA, LLMChain  # keep this comment
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.retrievers import EnsembleRetriever
from langchain.memory import (
    ConversationBufferMemory,  # chat history
    ConversationSummaryMemory,
)
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain.schema import Document
from langchain.storage import LocalFileStore
from langchain.embeddings import CacheBackedEmbeddings
from langchain.chat_models import init_chat_model
from langchain import hub
import langchain.chains.retrieval as retrieval_module
from langchain_core.messages import HumanMessage

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
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
    from langchain.agents import initialize_agent  # lazy import inside a function

    print(os.getcwd(), HumanMessage(content="hi"), Document(page_content="x"))
    print(initialize_agent, hub, retrieval_module)


if __name__ == "__main__":
    main()
