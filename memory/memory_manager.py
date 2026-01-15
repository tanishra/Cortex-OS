import json
import logging
from typing import Optional, List, Dict
from livekit.agents import ChatContext
from mem0 import AsyncMemoryClient
from dotenv import load_dotenv

load_dotenv()

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

            # Inject memory individually as separate messages
            for memory_item in memories:
                chat_ctx.add_message(role="assistant", content=memory_item["memory"])

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
            logger.info(
                "Starting save_chat_context | user_id=%s | items_count=%d",
                user_id,
                len(chat_ctx.items),
                )

            messages: List[Dict[str, str]] = []

            for idx, item in enumerate(chat_ctx.items):
                logger.debug(
                    "Processing chat_ctx item | user_id=%s | index=%d | role=%s | content_type=%s",
                    user_id,
                    idx,
                    getattr(item, "role", None),
                    type(item.content).__name__,
                    )

                content = (
                    "".join(item.content)
                    if isinstance(item.content, list)
                    else str(item.content)
                    )

                content = content.strip()

                logger.debug(
                    "Normalized content | user_id=%s | index=%d | content_len=%d",
                    user_id,
                    idx,
                    len(content),
                )

                # Skip empty content
                if not content:
                    logger.debug(
                        "Skipping empty content | user_id=%s | index=%d",
                        user_id,
                        idx,
                    )
                    continue

                # Skip injected memory to prevent duplication
                if injected_memory_str and injected_memory_str in content:
                    logger.debug(
                        "Skipping injected memory content | user_id=%s | index=%d | injected_len=%d",
                        user_id,
                        idx,
                        len(injected_memory_str),
                    )
                    continue

                if item.role not in ("user", "assistant"):
                    logger.debug(
                        "Skipping unsupported role | user_id=%s | index=%d | role=%s",
                        user_id,
                        idx,
                        item.role,
                    )
                    continue

                messages.append(
                    {
                        "role": item.role,
                        "content": content,
                    }
                )

                logger.debug(
                    "Message queued for persistence | user_id=%s | index=%d | role=%s",
                    user_id,
                    idx,
                    item.role,
                    )

            if not messages:
                logger.info(
                    "No messages collected for persistence | user_id=%s",
                    user_id,
                    )
                return

            logger.info(
                "Persisting messages to memory | user_id=%s | message_count=%d",
                user_id,
                len(messages),
            )

            logger.debug(
                "Messages payload preview | user_id=%s | messages=%s",
                user_id,
                messages,
            )

            await self.mem0.add(messages, user_id=user_id)
            
            logger.info(
                "Successfully saved chat context | user_id=%s | message_count=%d",
                user_id,
                len(messages),
            )

        except Exception as exc:
            logger.exception(
                "Failed to save chat context | user_id=%s | error=%s",
                user_id,
                exc,
            )