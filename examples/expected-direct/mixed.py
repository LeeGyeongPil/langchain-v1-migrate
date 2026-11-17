# import-check: skip
"""Imports that cannot be fixed automatically, and one that has to be split."""
from langchain.agents import create_agent  # one stays, one moved
from langchain_classic.agents import AgentExecutor
from langchain.prompts import PipelinePromptTemplate
from langchain.pydantic_v1 import BaseModel
import langchain.chains
from langchain_classic import hub
from langchain.agents import *
from langchain_community.chat_models import ChatAnthropic  # gone from langchain-community: warned, not guessed
