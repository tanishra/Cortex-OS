from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip
from livekit.plugins import (
    openai,
    noise_cancellation,
    anam
)
import os 
load_dotenv()

class Assistant(Agent):
    def __init__(self) -> None: 
        super().__init__(instructions="You are a helpful voice AI assistant.")

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        llm=openai.realtime.RealtimeModel(
            voice="coral"
        )
    )

    avatar = anam.AvatarSession(
        persona_config=anam.PersonaConfig(
            name="Mia",
            avatarId="edf6fdcb-acab-44b8-b974-ded72665ee26",
        ),
        api_key=os.getenv("ANAM_API_KEY"),
    )
    
    
    
    await avatar.start(session,room=ctx.room)

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
            video_input=True
        ),
    )

    background_audio = BackgroundAudioPlayer(
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING,volume=1),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2,volume=1)
        ]
    )
    await background_audio.start(room=ctx.room,agent_session=session)

    await session.generate_reply(
        instructions="Greet the user and offer your assistance. You should start by speaking in English."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)