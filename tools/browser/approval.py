import logging
from typing import Dict, Optional
from memory.store import MemoryManager

logger = logging.getLogger("JARVIS.Approval")

PENDING_ACTIONS: Dict[str, str] = {}
memory = MemoryManager()


async def request_approval(session_id: str, user_id: str, action: str) -> str:
    """
    Asynchronously requests user approval for a specific action.
    This function records the pending action associated with a session ID, logs the request,
    and adds a memory entry for the user indicating the pending approval. It then returns
    a prompt asking the user to confirm the action.
    Args:
        session_id (str): The unique identifier for the session.
        user_id (str): The unique identifier for the user.
        action (str): The action requiring user approval.
    Returns:
        str: A prompt message asking the user to confirm the action.
    """

    PENDING_ACTIONS[session_id] = action

    await memory.mem0.add(
        [{"memory": f"Pending approval: {action}"}],
        user_id=user_id,
    )

    logger.info("Approval requested for %s: %s", user_id, action)
    return f"Do you want me to proceed with: {action}? Please say yes or no."


async def handle_approval(session_id: str, user_response: str) -> Optional[str]:
    """
    Handles the approval process for a given session.
    This function checks if the provided session ID exists in the pending actions.
    If the user response indicates approval, the corresponding action is retrieved
    and logged as approved. Otherwise, the action is logged as denied, and the session
    is removed from the pending actions.
    Args:
        session_id (str): The unique identifier for the session.
        user_response (str): The user's response indicating approval or denial.
    Returns:
        Optional[str]: The approved action if the response is affirmative, 
        "Action cancelled." if the response is negative, or None if the session ID 
        is not found in the pending actions.
    """

    if session_id not in PENDING_ACTIONS:
        return None

    if user_response.lower() in ("yes", "confirm", "go ahead"):
        action = PENDING_ACTIONS.pop(session_id)
        logger.info("Approval granted: %s", action)
        return action

    PENDING_ACTIONS.pop(session_id)
    logger.info("Approval denied.")
    return "Action cancelled."