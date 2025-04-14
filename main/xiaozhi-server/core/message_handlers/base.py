# New file: main/xiaozhi-server/core/message_handlers/base.py

import abc

class BaseMessageHandler(abc.ABC):
    """Abstract base class for message handlers."""

    @abc.abstractmethod
    async def handle(self, message, context):
        """Handle an incoming message."""
        pass 