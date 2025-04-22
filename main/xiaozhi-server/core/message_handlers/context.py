from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Deque
from collections import deque

# Avoid circular imports with TYPE_CHECKING
# These imports will be needed when the classes are fully integrated
if TYPE_CHECKING:
    from ..channels.interface import ICommunicationChannel
    from ..config.config import Config
    from concurrent.futures import ThreadPoolExecutor
    from ..asr.interface import ASRInterface
    from ..vad.interface import VADInterface
    from ..llm.interface import LLMInterface
    from ..connection.tasks import TaskDispatcher
    from ..connection.state import StateManager
    from ..auth import AuthMiddleware
    import asyncio
    from asyncio import Queue
    from ..connection_handler import ConnectionHandler # Add ConnectionHandler import for type hint
    # Add other necessary type imports here

@dataclass
class HandlerContext:
    """Context object passed to message handlers, containing necessary dependencies and state."""

    # Core Dependencies (examples, adjust based on actual class names and paths)
    channel:                    'ICommunicationChannel'      # Communication channel
    config:                     'Config'                    # Application configuration
    logger:                     Any                           # Logger instance
    session_id:                 str                           # Unique connection ID
    executor:                   'ThreadPoolExecutor'        # For running blocking tasks
    asr:                        'ASRInterface'              # Automatic Speech Recognition service
    vad:                        'VADInterface'              # Voice Activity Detection service
    chat:                       'LLMInterface'              # Basic LLM chat service
    chat_with_function_calling: 'LLMInterface'              # LLM service with function calling
    dispatcher:                 'TaskDispatcher'            # Task dispatcher (from Step 5)
    state_manager:              'StateManager'              # State manager (from Step 4)
    auth:                       'AuthMiddleware'            # Authentication middleware (from Step 3)
    loop:                       'asyncio.AbstractEventLoop' # Event loop
    conn_handler:               'ConnectionHandler'         # Reference to the ConnectionHandler instance (temporary)
    # Queues (consider if these should be accessed via dispatcher)
    tts_queue:                  'Queue'                     # Queue for TTS requests
    audio_play_queue:           'Queue'                     # Queue for audio playback

    # Connection State (attributes previously on 'conn')
    cmd_exit:                   List[str] = field(default_factory=list) # Exit commands list
    asr_audio:                  Deque[bytes] = field(default_factory=lambda: deque(maxlen=50)) # Audio buffer for ASR
    asr_server_receive:         bool = True                   # ASR can receive audio
    client_listen_mode:         str = "auto"                # Client listening mode (e.g., "auto")
    client_have_voice:          bool = False                  # Is client currently sending voice?
    client_voice_stop:          bool = False                  # Has client indicated voice stop?
    client_no_voice_last_time:  float = 0.0                   # Timestamp of last silence detection
    client_abort:               bool = False                  # Client requested abort
    client_speak:               bool = False                  # Is server currently speaking (TTS)?
    client_speak_last_time:     float = 0.0                   # Timestamp when server last started speaking
    use_function_call_mode:     bool = False                  # Use LLM function calling?
    close_after_chat:           bool = False                  # Close connection after current chat?

    # Other potential state/dependencies (Add as needed)
    # memory: Any = None
    # private_config: Any = None

    # Helper method to get VAD (could be a property)
    # def get_vad_instance(self) -> 'VADInterface':
    #     return self.vad

    # Add methods for state manipulation if needed, e.g.:
    def reset_vad_states(self):
        # Corresponds to original conn.reset_vad_states()
        self.client_have_voice = False
        self.client_voice_stop = False
        # Add other VAD state resets if necessary
        self.logger.bind(tag="HandlerContext").debug("VAD states reset")

    # Placeholder for other attributes/methods potentially needed
    def __post_init__(self):
        # Ensure logger is available if not passed explicitly, maybe get default logger?
        if not hasattr(self, 'logger') or self.logger is None:
            # This is tricky, ideally logger is always injected.
            # As a fallback, import and setup default logger here?
            from config.logger import setup_logging
            self.logger = setup_logging() # Or get a pre-configured logger instance 