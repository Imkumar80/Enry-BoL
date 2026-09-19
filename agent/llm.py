import os
from langchain_ollama import ChatOllama
from agent.tools import TOOLS_LIST

class LocalLLM:
    """
    Adapter for local Ollama models. 
    Allows hot-swapping models via environment variables without changing graph logic.
    """
    def __init__(self):
        # Defaulting to 3B parameters as the RTX 2050 has 4GB VRAM.
        # qwen2.5:7b requires ~4.7GB VRAM for 4-bit, which would OOM.
        model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        print(f"Initializing LocalLLM with model: {model_name} at {base_url}")
        
        self.llm = ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0.1
        )
        
        # Bind the DB operations as LangChain tools
        self.llm_with_tools = self.llm.bind_tools(TOOLS_LIST)

    async def generate(self, messages: list):
        """Invoke the LLM with the message history."""
        return await self.llm_with_tools.ainvoke(messages)
