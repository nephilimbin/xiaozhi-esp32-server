# New file: main/xiaozhi-server/core/message_handlers/audio.py

from .base import BaseMessageHandler
# Import HandlerContext when types are uncommented
# from .context import HandlerContext

class AudioMessageHandler(BaseMessageHandler):
    """Handles incoming audio messages/data."""

    async def handle(self, message, context):
        # Placeholder - implement actual audio message handling logic
        # This might involve sending audio to STT or other processing
        print(f"Placeholder: Handling audio message (size: {len(message) if isinstance(message, bytes) else 'N/A'})")
        # Example: await context.dispatcher.dispatch_stt_task(message)
        pass 