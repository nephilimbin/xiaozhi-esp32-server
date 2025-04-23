# New file: main/xiaozhi-server/core/routing.py
# Import handlers when needed
from core.message_handlers.base import BaseMessageHandler
from core.message_handlers.text import TextMessageHandler
from core.message_handlers.audio import AudioMessageHandler
from config.logger import setup_logging


logger = setup_logging()
TAG = __name__

class MessageRouter:
    def __init__(self):
        # Initialize handlers - potentially make these singletons or manage differently
        self._text_handler = TextMessageHandler()
        self._audio_handler = AudioMessageHandler()
        # Add other handlers if needed

    def route(self, message) -> BaseMessageHandler | None:
        """Determine the appropriate handler for the message."""
        # Simple routing based on message type
        if isinstance(message, str):
            # Could add more logic here based on message content (e.g., JSON type field)
            # For now, assume string is text
            return self._text_handler
        elif isinstance(message, bytes):
            return self._audio_handler

        # Return None or a default handler if type is unknown
        logger.bind(tag=TAG).warning(f"Unknown message type for routing: {type(message)}")
        return None
    

