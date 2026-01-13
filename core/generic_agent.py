from livekit.agents import Agent
from livekit.agents.job import get_job_context
from livekit.agents.llm import function_tool
from livekit import rtc, api

class GenericAgent(Agent):
    # Automatically greet the user when entering the call
    async def on_enter(self):
        self.session.generate_reply()
    
    # Automatically end the conversation when user request it
    @function_tool
    async def end_conversation(self):
        """Call this function when the user wants to end conversation"""

        self.session.interrupt()

        await self.session.generate_reply(
            instructions=f"Say goodbye", allow_interruptions=False
        )

        jobx_ctx = get_job_context()
        await jobx_ctx.api.room.delete_room(api.DeleteRoomRequest(room=jobx_ctx.room.name))
