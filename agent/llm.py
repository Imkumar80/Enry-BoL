"""
agent/llm.py — Ollama LLM Adapter for LangGraph
==================================================
Uses langchain-ollama to connect to a local Ollama instance.
Model and URL are configured via environment variables.
"""

import os
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from agent.tools import TOOLS_LIST

logger = logging.getLogger("agent.llm")

_llm_instance = None


def get_llm():
    """Get or create the LLM instance with tools bound."""
    global _llm_instance
    if _llm_instance is None:
        api_key = os.getenv("GEMINI_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is missing from environment")

        logger.info(f"Initializing Gemini LLM: {model_name}")

        llm = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=0.1,
        )

        _llm_instance = llm.bind_tools(TOOLS_LIST)
    return _llm_instance
