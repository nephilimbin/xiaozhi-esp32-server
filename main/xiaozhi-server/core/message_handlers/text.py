# New file: main/xiaozhi-server/core/message_handlers/text.py

from .base import BaseMessageHandler
# Import HandlerContext when types are uncommented
# from .context import HandlerContext

class TextMessageHandler(BaseMessageHandler):
    """Handles incoming text messages."""

    async def handle(self, message, context):
        # Placeholder - implement actual text message handling logic
        print(f"Placeholder: Handling text message: {message}")
        # Example: await context.websocket.send_text("Received your text")
        pass 