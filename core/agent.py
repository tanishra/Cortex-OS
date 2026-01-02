import logging
import asyncio
import os

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, ChatContext
from livekit.plugins import (
    openai,
    noise_cancellation,
)

from mcp_client import MCPServerSse
from mcp_client.agent_tools import MCPToolsIntegration

from config.settings import settings
from config.logging import setup_logging
from prompts.system_prompt import SYSTEM_PROMPT
from prompts.session_prompt import SESSION_PROMPT

from tools import (
   search,
    get_weather,
    send_email,
    open_file,
    list_directory,
    create_folder,
    delete_path,
    run_command,
    scrape_page,
    write_file,
    read_file,
    move_file,
    delete_file,
    copy_file,
    open_url,
    search_youtube,
    search_google,
    open_github,
    open_stackoverflow
)

from memory.memory_manager import MemoryManager


setup_logging()
logger = logging.getLogger("JARVIS.Agent")

tools = [
  search,
    get_weather,
    send_email,
    open_file,
    list_directory,
    create_folder,
    delete_path,
    run_command,
    scrape_page,
    write_file,
    read_file,
    move_file,
    delete_file,
    copy_file,
    open_url,
    search_youtube,
    search_google,
    open_github,
    open_stackoverflow
]


class Assistant(Agent):
    def __init__(self, chat_ctx=None) -> None:
        logger.info("Initializing Assistant agent")
        super().__init__(
            instructions=SYSTEM_PROMPT,
            llm=openai.realtime.RealtimeModel(
                api_key=settings.openai.api_key,
                model=settings.openai.model,
                voice="marin",
                temperature=0.1,
            ),
            tools=tools,
            chat_ctx=chat_ctx,
        )
        logger.info("Assistant initialized successfully")


server = AgentServer()


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    logger.info("RTC session started")

    session = AgentSession()

    user_name = "Tanish"  # TODO: replace with ctx.participant.identity in prod
    initial_ctx = ChatContext()

    memory_manager = MemoryManager()

    # Load and inject memory
    memory_str = await memory_manager.load_user_memory(
        user_id=user_name,
        chat_ctx=initial_ctx,
    )

    mcp_server = MCPServerSse(
        params={"url": os.environ.get("N8N_MCP_SERVER_URL")},
        cache_tools_list=True,
        name="SSE MCP Server",
    )

    agent = await MCPToolsIntegration.create_agent_with_tools(
        agent_class=Assistant,
        agent_kwargs={"chat_ctx": initial_ctx},
        mcp_servers=[mcp_server],
    )

    try:
        await session.start(
            room=ctx.room,
            agent=agent,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC(),
                ),
            ),
        )
        logger.info("Agent session started successfully")

        await session.generate_reply(
            instructions=SESSION_PROMPT,
        )
        logger.info("Initial session prompt delivered")

        chat_ctx = agent.chat_ctx

        ctx.add_shutdown_callback(
            lambda: asyncio.create_task(
                memory_manager.save_chat_context(
                    user_id=user_name,
                    chat_ctx=chat_ctx,
                    injected_memory_str=memory_str,
                )
            )
        )

    except Exception as e:
        logger.exception("Fatal error in RTC session", exc_info=e)
        raise


if __name__ == "__main__":
    logger.info("Starting Voice Agent Server")
    agents.cli.run_app(server)