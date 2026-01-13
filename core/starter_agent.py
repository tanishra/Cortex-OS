from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.agents.llm import function_tool, ChatContext
from livekit.plugins import (
    openai,
    noise_cancellation,
    deepgram
)

from generic_agent import GenericAgent
load_dotenv()

class StarterAgent(GenericAgent):
    def __init__(self,chat_ctx : ChatContext = None) -> None:
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
                            Greet the user by saying your name is Tanish
                            Use the tool call_support_agent when the user has a technical issue.
                            If the chat context is not empty, reference it when greeting the user and also say something like 'Welcome back'   """,
            llm=openai.realtime.RealtimeModel(voice="echo"),
            chat_ctx=chat_ctx
            )
    
    @function_tool
    async def call_support_agent(self,topic : str):
        """
        Call When the user has a technical issue

        Args:
            topic: Topic of the technical issue

        """
        
        support_agent = SupportAgent(topic=topic)
        return support_agent , f"Connecting you to our support agent Sourabh with the topic of {topic}."
    

    @function_tool
    async def call_booking_agent(self,appointment_topic : str):
        """
        Call When the user wants to book appointment

        Args:
            appointment_topic: Topic of the appointment

        """
        
        support_agent = BookingAgent(appointment_topic=appointment_topic)
        return support_agent , f"Connecting you to our booking agent Jessica with the topic of {appointment_topic}."

class SupportAgent(GenericAgent):
    def __init__(self,topic: str) -> None:
        super().__init__(
            instructions=f"""You are a helpful voice AI assistant.
                            Greet the user by saying your name is Sourabh.
                            The topic of the technical issue is {topic}.
                            When the issue is resolved, ask the user if they want to talk to Tanish again.
                            If not end the conversation with the tool end_conversation.""",
            llm=openai.realtime.RealtimeModel(modalities=['text']),
            tts=deepgram.TTS(
                model="aura-asteria-en"
            )) 
    
    @function_tool
    async def call_starter_agent(self):
        """Call When the user wants to talk to Tanish again"""
        
        chat_ctx = self.chat_ctx
        support_agent = StarterAgent(chat_ctx=chat_ctx)
        return support_agent , "Connecting you back to Tanish"
    
class BookingAgent(GenericAgent):
    def __init__(self,appointment_topic: str) -> None:
        super().__init__(
            instructions=f"""You are a helpful voice AI assistant.
                            Greet the user by saying your name is Jessica.
                            The topic of the booking is {appointment_topic}.
                            When the booking was successful, ask the user if they want to talk to Tanish again.
                            If not end the conversation with the tool end_conversation""",
            llm=openai.realtime.RealtimeModel(modalities=['text']),
            tts=deepgram.TTS(
                model="aura-asteria-en"
            )) 
    
    @function_tool
    async def call_starter_agent(self):
        """Call When the user wants to talk to Tanish again"""
        
        chat_ctx = self.chat_ctx
        support_agent = StarterAgent(chat_ctx=chat_ctx)
        return support_agent , "Connecting you back to Tanish"
        
server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        
    )

    await session.start(
        room=ctx.room,
        agent=StarterAgent(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

if __name__ == "__main__":
    agents.cli.run_app(server)