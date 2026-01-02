import json
import logging
from typing import Optional, List, Dict

from livekit.agents import ChatContext
from mem0 import AsyncMemoryClient

logger = logging.getLogger("MemoryManager")


class MemoryManager:
    """
    Handles loading, injecting, and persisting conversational memory
    using Mem0 in a production-safe manner.
    """

    def __init__(self, mem0_client: Optional[AsyncMemoryClient] = None):
        self.mem0 = mem0_client or AsyncMemoryClient()

    async def load_user_memory(
        self,
        user_id: str,
        chat_ctx: ChatContext,
    ) -> str:
        """
        Loads previous memories for a user and injects them
        into the ChatContext.

        Returns:
            memory_str (str): Serialized memory injected into context
        """
        try:
            logger.info("Loading memory for user_id=%s", user_id)

            results = await self.mem0.get_all(
                filters={
                    "OR": [{"user_id": user_id}]
                }
            )

            if not results or not results.get("results"):
                logger.info("No existing memory found for user_id=%s", user_id)
                return ""

            memories = [
                {
                    "memory": item.get("memory"),
                    "updated_at": item.get("updated_at"),
                }
                for item in results["results"]
            ]

            memory_str = json.dumps(memories, indent=2)

            chat_ctx.add_message(
                role="assistant",
                content=(
                    f"The user's name is {user_id} and this is relevant context "
                    f"about him:\n{memory_str}"
                ),
            )

            logger.info(
                "Injected %d memory items into chat context for user_id=%s",
                len(memories),
                user_id,
            )

            return memory_str

        except Exception:
            logger.exception(
                "Failed to load or inject memory for user_id=%s", user_id
            )
            return ""

    async def save_chat_context(
        self,
        user_id: str,
        chat_ctx: ChatContext,
        injected_memory_str: str,
    ) -> None:
        """
        Persists relevant chat messages to memory,
        excluding injected memory context.
        """
        try:
            logger.info("Saving chat context to memory for user_id=%s", user_id)

            messages: List[Dict[str, str]] = []

            for item in chat_ctx.items:
                content = (
                    "".join(item.content)
                    if isinstance(item.content, list)
                    else str(item.content)
                )

                # Skip injected memory to prevent duplication
                if injected_memory_str and injected_memory_str in content:
                    continue

                if item.role in ("user", "assistant"):
                    messages.append(
                        {
                            "role": item.role,
                            "content": content.strip(),
                        }
                    )

            if not messages:
                logger.info("No new messages to save for user_id=%s", user_id)
                return

            await self.mem0.add(messages, user_id=user_id)

            logger.info(
                "Successfully saved %d messages to memory for user_id=%s",
                len(messages),
                user_id,
            )

        except Exception:
            logger.exception(
                "Failed to save chat context for user_id=%s", user_id
            )