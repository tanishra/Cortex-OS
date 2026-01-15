from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, ChatContext
from livekit.plugins import (
    openai,
    noise_cancellation,
)
from mem0 import AsyncMemoryClient
import json
import logging
load_dotenv()

class Assistant(Agent):
    def __init__(self,chat_ctx = None) -> None:
        super().__init__(instructions="You are a helpful voice AI assistant.")
        chat_ctx = chat_ctx

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    async def shutdown_hook(chat_ctx : ChatContext,mem0 : AsyncMemoryClient,memory_str : str):
        logging.info("Shutting down, saving chat context to memory")
        messages_formatted = []

        logging.info(f"Chat context messages : {chat_ctx.items}")

        for item in chat_ctx.items:
            content_str = "".join(item.content) if isinstance(item.content,list) else str(item.content)

            if memory_str and memory_str in content_str:
                continue

            if item.role in ['user','assistant']:
                messages_formatted.append({
                    "role" : item.role,
                    "content" : content_str.strip()
                })
        
        logging.info(f"Formatted messages to add to memory : {messages_formatted}")
        await mem0.add(messages_formatted,user_id="Tanish")
        logging.info(f"Chat context saved to memory")

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="coral"
        )
    )

    memo0 = AsyncMemoryClient()
    user_name = "Tanish"

    results = await memo0.get_all(filters={"AND": [{"user_id": user_name}]})
    initial_ctx = ChatContext()
    memory_str = ""

    if results:
        memories = [
            {
                "memory" : result['memory'],
                "updated_at" : result['updated_at']
            }
            for result in results['results']
        ]

        memory_str = json.dumps(memories)
        logging.info(f"memory str : {memory_str}")
        initial_ctx.add_message(role='assistant',content=f"The user's name is {user_name} and this is relevant information about the user is {memory_str}")

    await session.start(
        room=ctx.room,
        agent=Assistant(chat_ctx=initial_ctx),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    await session.generate_reply(
        instructions="Greet the user and offer your assistance. You should start by speaking in English."
    )

    ctx.add_shutdown_callback(lambda : shutdown_hook(session._agent.chat_ctx,memo0,memory_str))


if __name__ == "__main__":
    agents.cli.run_app(server)