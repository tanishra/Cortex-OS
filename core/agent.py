import logging
import asyncio
import os

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, ChatContext
from livekit.plugins import (
    openai,
    noise_cancellation,
    deepgram,
    anam
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
    open_stackoverflow,
    open_app,
    quit_app,
    focus_app,
    list_apps,
    open_new_tab,
    click_element,
    switch_tab,
    scroll_page,
    search_on_page,
    go_back,
    go_forward,
    close_current_tab,
    close_all_tabs,
    close_tab_by_index,
    close_tab_by_title,
    submit_search,
    smart_click
)

from memory.memory_manager import MemoryManager
from dotenv import load_dotenv

load_dotenv()


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
    open_stackoverflow,
    open_app,
    focus_app,
    quit_app,
    list_apps,
    open_new_tab,
    click_element,
    switch_tab,
    scroll_page,
    search_on_page,
    go_back,
    go_forward,
    close_current_tab,
    close_all_tabs,
    close_tab_by_index,
    close_tab_by_title,
    smart_click,
    submit_search
]


class Assistant(Agent):
    def __init__(self, chat_ctx=None,memory_manager=None,user_id=None) -> None:
        logger.info("Initializing Assistant agent")
        super().__init__(
            instructions=SYSTEM_PROMPT,
            llm=openai.realtime.RealtimeModel(
                api_key=settings.openai.api_key,
                model=settings.openai.model,
                modalities=['text'],
                temperature=0.1,
            ),
            tts=deepgram.TTS(model="aura-2-callista-en"),
            tools=tools,
            chat_ctx=chat_ctx,
        )
        self.memory_manager=memory_manager,
        self.user_id=user_id
        logger.info("Assistant initialized successfully")
    
    async def on_user_turn_completed(self, turn_ctx, new_message):
        """Save memory after each user turn"""
        if self.memory_manager and self.user_id:
            try:
                custom_instructions = """
                Only extract important preferences, facts, and explicit requests to remember.
                Ignore greetings, small talk, and casual conversation.
                """
                
                # Save the user message to Mem0
                await self.memory_manager.mem0.add(
                    [{"role": "user", "content": new_message.text_content}],
                    user_id=self.user_id
                )
                logger.info(f"Saved user message to memory: {new_message.text_content[:50]}...")
            except Exception as e:
                logger.error(f"Failed to save memory: {e}")
        
        await super().on_user_turn_completed(turn_ctx, new_message)


server = AgentServer()


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    logger.info("RTC session started")

    session = AgentSession()

    avatar = anam.AvatarSession(
        persona_config=anam.PersonaConfig(
            name="Mia",
            avatarId="edf6fdcb-acab-44b8-b974-ded72665ee26",
        ),
        api_key=os.getenv("ANAM_API_KEY"),
    )

    user_name = "tanish"  # TODO: replace with ctx.participant.identity in prod
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
        await avatar.start(session, room=ctx.room)
        
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

    except Exception as e:
        logger.exception("Fatal error in RTC session", exc_info=e)
        raise


if __name__ == "__main__":
    logger.info("Starting Voice Agent Server")
    agents.cli.run_app(server)