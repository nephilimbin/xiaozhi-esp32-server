from dataclasses import dataclass
from typing import TYPE_CHECKING

# Avoid circular imports with TYPE_CHECKING
# These imports will be needed when the classes are defined
# if TYPE_CHECKING:
#     from core.tasks import TaskDispatcher
#     from core.channels.websocket_wrapper import WebSocketWrapper
#     from core.state import StateManager

@dataclass
class HandlerContext:
    """Context object passed to message handlers."""
    # Temporarily comment out type hints until classes are defined
    # dispatcher: 'TaskDispatcher'
    # websocket: 'WebSocketWrapper'
    # state_manager: 'StateManager'
    # Add other necessary context items here
    pass 