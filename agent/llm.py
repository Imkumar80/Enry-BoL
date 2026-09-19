"""
agent/llm.py — Ollama LLM Adapter for LangGraph
==================================================
Uses langchain-ollama to connect to a local Ollama instance.
Model and URL are configured via environment variables.
"""

import os
import logging
from langchain_ollama import ChatOllama
from agent.tools import TOOLS_LIST

logger = logging.getLogger("agent.llm")

_llm_instance = None


def get_llm():
    """Get or create the LLM instance with tools bound."""
    global _llm_instance
    if _llm_instance is None:
        model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        logger.info(f"Initializing Ollama LLM: {model_name} at {base_url}")

        llm = ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0.1,
            num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "96")),
        )

        _llm_instance = llm.bind_tools(TOOLS_LIST)
    return _llm_instance
