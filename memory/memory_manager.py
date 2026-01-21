import json
import logging
from typing import Optional, List, Dict
from livekit.agents import ChatContext
from mem0 import AsyncMemoryClient
from prompts.mem0_prompt import MEM0_PROMPT
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
        
        # Set project-level custom instructions (runs once on init)
        self._setup_custom_instructions()
        
    def _setup_custom_instructions(self):
        """Configure what Mem0 should store and ignore."""
        
        try:
            custom_instructions = MEM0_PROMPT
            self.mem0.project.update(custom_instructions=custom_instructions)
            logger.info("Custom instructions configured for Mem0 project")
        except Exception as e:
            logger.warning(f"Failed to set custom instructions: {e}")

    async def load_user_memory(
        self,
        user_id: str,
        chat_ctx: ChatContext,
    ) -> str:
        """
        Loads previous memories for a user and injects them
        into the ChatContext.
        """
        try:
            logger.info("Loading memory for user_id=%s", user_id)

            # --- V2 API UPDATE ---
            # We must use the 'filters' parameter with the 'AND' operator
            # as per the Mem0 documentation.
            results = await self.mem0.get_all(
                # filters={
                #     "AND": [{"user_id": user_id}]
                # }
                filters={"user_id": user_id}
            )

            # Handle response structure (Mem0 returns a dict with 'results' key)
            if not results or not isinstance(results, dict) or not results.get("results"):
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

        except Exception as e:
            logger.exception(
                "Failed to load or inject memory for user_id=%s. Error: %s", user_id, str(e)
            )
            return ""

    async def save_chat_context(
            self,
            user_id: str,
            chat_ctx: ChatContext,
            injected_memory_str: str,
            ) -> None:
        try:
            logger.info("Starting save_chat_context | user_id=%s", user_id)

            messages: List[Dict[str, str]] = []
            items_to_process = getattr(chat_ctx, "messages", [])
        
            logger.info(f"Total messages to process: {len(items_to_process)}")

            for idx, item in enumerate(items_to_process):
                # Debug logging
                logger.debug(f"Processing message {idx}: type={type(item)}, has_content={hasattr(item, 'content')}")
            
                if not hasattr(item, "content") or item.content is None:
                    continue

                if not hasattr(item, "role"):
                    continue

                # Handle content - could be string or list
                content = item.content
                if isinstance(content, list):
                    content = "".join(str(c) for c in content)
                else:
                    content = str(content)
                content = content.strip()

                if not content:
                    logger.debug(f"Skipping message {idx}: empty content")
                    continue

                # Get role as string
                role_val = item.role
                role_str = str(role_val.value if hasattr(role_val, "value") else role_val).lower()

                if role_str not in ["user", "assistant"]:
                    logger.debug(f"Skipping message {idx}: role={role_str}")
                    continue

                # Skip JSON tool calls
                if content.lstrip().startswith("{") and "function" in content:
                    continue

                messages.append({"role": role_str, "content": content})
                logger.debug(f"Added message {idx}: role={role_str}, content_len={len(content)}")

            logger.info(f"Valid messages to persist: {len(messages)}")

            if not messages:
                logger.info("No valid text messages to persist.")
                return

            result = await self.mem0.add(messages, user_id=user_id)
            logger.info(f"Mem0 add result: {result}")

        except Exception as exc:
            logger.exception("Failed to save chat context | user_id=%s | error=%s", user_id, exc)