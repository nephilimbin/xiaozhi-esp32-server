from abc import ABC, abstractmethod
from typing import Any

class ICommunicationChannel(ABC):
    """
    Abstract base class defining the interface for communication channels.
    Handlers should depend on this interface, not concrete implementations.
    """

    @abstractmethod
    async def send_message(self, message: dict[str, Any]) -> None:
        """
        Sends a structured message (typically dict) through the channel.
        Concrete implementations handle serialization (e.g., to JSON).
        """
        pass

    @abstractmethod
    async def send_raw_string(self, text: str) -> None:
        """
        Sends a raw string message through the channel.
        Useful for cases where no specific structure or serialization is needed.
        """
        pass

    @abstractmethod
    async def send_bytes(self, data: bytes) -> None:
        """
        Sends raw bytes data through the channel.
        Useful for cases where no specific structure or serialization is needed.
        """
        pass


    # Helper methods can remain here or be moved if they don't rely on abstract state
    # Or they can be implemented by concrete classes if preferred
    async def send_json(self, data: dict[str, Any]) -> None:
        """
        Helper method to send data as a JSON string.
        This default implementation calls send_message.
        """
        await self.send_message(data)

    async def send_text(self, text: str) -> None:
        """
        Helper method to send plain text, wrapping it in a standard format if necessary.
        This assumes a simple {"type": "text", "content": text} structure.
        Adjust the structure based on your application's protocol.
        """
        await self.send_message({"type": "text", "content": text}) 