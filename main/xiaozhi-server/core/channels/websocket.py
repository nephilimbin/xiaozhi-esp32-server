import json
from typing import Any
import websockets # Import at top level might be okay here if only used by this class

from config.logger import setup_logging
from .interface import ICommunicationChannel # Import the interface from the same directory

# Initialize logger at module level
logger = setup_logging()
TAG = __name__ # Define a tag for context

# Concrete implementation for WebSocket communication
class WebSocketChannel(ICommunicationChannel):
    def __init__(self, websocket):
        self.websocket = websocket
        # Store session_id if available, for logging context
        self.session_id = getattr(websocket, 'id', getattr(websocket, 'session_id', 'N/A'))

    async def send_message(self, message: dict[str, Any]) -> None:
        """
        Sends a dictionary as a JSON string over the WebSocket connection.
        Overrides the abstract method from ICommunicationChannel.
        Relies on exception handling for closed connections.
        """
        if self.websocket:
            try:
                json_message = json.dumps(message, ensure_ascii=False)
                await self.websocket.send(json_message)
            except websockets.exceptions.ConnectionClosed:
                logger.bind(tag=TAG).warning(f"Attempted to send message on closed WebSocket. Session: {self.session_id}")
            except Exception as e:
                logger.bind(tag=TAG).error(f"Error sending WebSocket JSON message: {e}. Session: {self.session_id}", exc_info=True)
        else:
            logger.bind(tag=TAG).error("WebSocket is not initialized for send_message.")

    async def send_raw_string(self, text: str) -> None:
        """
        Sends a raw string directly over the WebSocket connection.
        Overrides the abstract method from ICommunicationChannel.
        Relies on exception handling for closed connections.
        """
        if self.websocket:
            try:
                await self.websocket.send(text)
            except websockets.exceptions.ConnectionClosed:
                logger.bind(tag=TAG).warning(f"Attempted to send raw string on closed WebSocket. Session: {self.session_id}")
            except Exception as e:
                logger.bind(tag=TAG).error(f"Error sending WebSocket raw string: {e}. Session: {self.session_id}", exc_info=True)
        else:
            logger.bind(tag=TAG).error("WebSocket is not initialized for send_raw_string.")

    # Override helper methods if specific behavior is needed for WebSocket
    # For now, inheriting the default send_json and send_text which call
    # the implemented send_message should be fine.

    # Implement other methods like close, is_active if needed from the interface 