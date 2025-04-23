from dataclasses import dataclass, field
from typing import Any, List, Deque
from collections import deque
from config.logger import setup_logging
from concurrent.futures import ThreadPoolExecutor
from core.channels.interface import ICommunicationChannel
from core.connection.tasks import TaskDispatcher
from core.connection.state import StateManager
from core.auth import AuthMiddleware
import asyncio
from asyncio import Queue

@dataclass
class HandlerContext:
    """Context object passed to message handlers, containing necessary dependencies and state."""

    channel: ICommunicationChannel
    config: Any
    session_id: str
    executor: ThreadPoolExecutor
    asr: Any
    vad: Any
    llm: Any
    dispatcher: TaskDispatcher
    state_manager: StateManager
    auth: AuthMiddleware
    loop: asyncio.AbstractEventLoop
    tts_queue: Queue
    audio_play_queue: Queue
    conn_handler: Any # TODO 临时为了代码正常测试和迁移，迁移后删除。
    cmd_exit: List[str]
    asr_server_receive: bool
    client_listen_mode: str
    client_have_voice: bool
    client_voice_stop: bool
    client_no_voice_last_time: float
    client_abort: bool
    use_function_call_mode: bool
    close_after_chat: bool
    client_speak: bool
    client_speak_last_time: float
    logger: Any = field(default_factory=setup_logging)
    asr_audio: Deque[bytes] = field(default_factory=deque)

    # Add methods for state manipulation if needed, e.g.:
    def reset_vad_states(self):
        # Corresponds to original conn.reset_vad_states()
        self.client_have_voice = False
        self.client_voice_stop = False
        # Add other VAD state resets if necessary
        self.logger.bind(tag="HandlerContext").debug("VAD states reset")
