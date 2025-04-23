# New file: main/xiaozhi-server/core/tasks.py

import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
import queue
from typing import Any, Callable, Tuple


class TaskDispatcher:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
        tts_queue: queue.Queue,
        audio_queue: queue.Queue,
    ):
        self.loop = loop
        self.executor = executor
        self.tts_queue = tts_queue
        self.audio_queue = audio_queue

    def dispatch_plugin_task(self, func: Callable[..., Any], *args: Any) -> Future:
        # 运行同步函数 func 在 executor 中，返回 Future 对象
        # The call site will decide whether to await this Future or not.
        # Note: Using concurrent.futures.Future for executor tasks
        return self.executor.submit(func, *args)

    def dispatch_tts(self, future: Future):
        # 将代表 TTS 任务的 Future 对象放入 TTS 队列
        # The Future is expected to resolve to (tts_file, text, text_index)
        try:
            self.tts_queue.put_nowait(future)
        except queue.Full:
            # Handle queue full scenario if necessary, e.g., log a warning
            print("Warning: TTS queue is full.")  # Or use proper logging
            # Optionally, handle the future (e.g., cancel it)
            future.cancel()
            pass

    # Using Tuple[Any, ...] to represent the varied structures put into the audio queue
    def dispatch_audio(self, data_tuple: Tuple[Any, ...]):
        # 将包含音频数据和元数据的元组放入播放队列
        # Expected formats include:
        # (mp3_data, text, text_index, 'mp3')
        # (opus_blob_with_len, text, text_index, 'opus_blob')
        # (text_index, (opus_packets, response_text, text_index)) # from chat_async
        try:
            self.audio_queue.put_nowait(data_tuple)
        except queue.Full:
            # Handle queue full scenario if necessary
            print("Warning: Audio play queue is full.")  # Or use proper logging
            pass
