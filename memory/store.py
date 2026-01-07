import json
import logging
from typing import Optional, List, Dict

from livekit.agents import ChatContext
from mem0 import AsyncMemoryClient

logger = logging.getLogger("JARVIS.Memory")


class MemoryManager:
    """
    Production-grade memory manager using Mem0.
    Stores only salient user knowledge, not full chat logs.
    """

    def __init__(self, mem0_client: Optional[AsyncMemoryClient] = None):
        self.mem0 = mem0_client or AsyncMemoryClient()

    async def load_user_memory(self, user_id: str, chat_ctx: ChatContext) -> None:
        try:
            logger.info("Loading memory for user_id=%s", user_id)

            results = await self.mem0.search(
                query="user preferences, personal facts, workflow habits",
                filters={"user_id": user_id},
                limit=20,
            )

            if not results or not results.get("results"):
                logger.info("No memory found for user_id=%s", user_id)
                return

            memories = [item["memory"] for item in results["results"]]

            memory_block = "\n".join(f"- {m}" for m in memories)

            chat_ctx.add_message(
                role="system",
                content=f"Known user context:\n{memory_block}",
            )

            logger.info("Injected %d memory items for user_id=%s", len(memories), user_id)

        except Exception:
            logger.exception("Memory injection failed")

    async def save_chat_context(self, user_id: str, chat_ctx: ChatContext) -> None:
        try:
            logger.info("Extracting memory from conversation")

            raw_text = "\n".join(
                f"{item.role}: {item.content}"
                for item in chat_ctx.items
                if item.role in ("user", "assistant")
            )

            if not raw_text.strip():
                return

            extracted = await self.mem0.extract(raw_text)

            if not extracted or not extracted.get("memories"):
                logger.info("No new memory extracted")
                return

            await self.mem0.add(
                extracted["memories"],
                user_id=user_id,
            )

            logger.info("Saved %d memory entries for user_id=%s",
                        len(extracted["memories"]), user_id)

        except Exception:
            logger.exception("Memory save failed")