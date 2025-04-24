from dataclasses import dataclass, field
from typing import Any, List, Deque, Dict
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import asyncio
from asyncio import Queue
from core.channels.websocket import WebSocketChannel
import threading
from core.utils.dialogue import Message, Dialogue
from core.utils.util import get_string_no_punctuation_or_emoji
from core.utils.util import extract_json_from_string
import time
import json
import uuid

TAG = __name__


@dataclass
class HandlerContext:
    """Context object passed to message handlers, containing necessary dependencies and state."""

    vad: Any
    asr: Any
    llm: Any
    tts: Any
    memory: Any
    intent: Any
    config: Any
    websocket: Any
    logger: Any
    channel: WebSocketChannel
    client_ip_info: Dict[str, Any]
    session_id: str
    prompt: str
    welcome_msg: str
    # 线程任务相关
    loop: asyncio.AbstractEventLoop
    stop_event: threading.Event
    tts_queue: Queue
    audio_play_queue: Queue
    executor: ThreadPoolExecutor
    # TODO 临时为了代码正常测试和迁移，迁移后删除。
    # conn_handler: Any

    # 任务调度器
    dispatcher: Any
    router: Any  # 消息路由器
    state_manager: Any  # 状态管理器

    # 客户端状态相关
    client_abort: bool = field(default=False)
    client_listen_mode: str = field(default="auto")
    client_audio_buffer: bytearray = field(default_factory=bytearray)
    client_have_voice: bool = field(default=False)
    client_have_voice_last_time: float = field(default=0.0)
    client_no_voice_last_time: float = field(default=0.0)
    client_voice_stop: bool = field(default=False)

    # asr相关变量
    asr_audio: List[bytes] = field(default_factory=list)
    asr_server_receive: bool = field(default=True)

    # llm相关变量
    llm_finish_task: bool = field(default=False)
    dialogue: Dialogue = field(default_factory=Dialogue)

    # tts相关变量
    tts_first_text_index: int = field(default=-1)
    tts_last_text_index: int = field(default=-1)

    # iot相关变量
    iot_descriptors: Dict[str, Any] = field(default_factory=dict)
    func_handler: Any = field(default=None)

    # 函数调用相关变量
    use_function_call_mode: bool = field(default=False)

    # 退出命令相关变量
    cmd_exit: Any = field(default=None)
    max_cmd_length: int = field(default=0)

    def __post_init__(self):
        if self.config and "exit_commands" in self.config:
            self.cmd_exit = self.config["exit_commands"]
            self.max_cmd_length = 0
            if isinstance(self.cmd_exit, list):
                for cmd in self.cmd_exit:
                    if isinstance(cmd, str) and len(cmd) > self.max_cmd_length:
                        self.max_cmd_length = len(cmd)
            elif isinstance(self.cmd_exit, str):
                self.max_cmd_length = len(self.cmd_exit)
        else:
            self.cmd_exit = []  # 提供一个默认的空列表
            self.max_cmd_length = 0

    # Add methods for state manipulation if needed, e.g.:
    def reset_vad_states(self):
        # Corresponds to original conn.reset_vad_states()
        self.client_have_voice = False
        self.client_voice_stop = False
        # Add other VAD state resets if necessary
        self.logger.bind(tag="HandlerContext").debug("VAD states reset")

    async def _route_message(self, message):
        """消息路由 - Step 8a': Route Text to Handler"""
        # Moved imports here to break circular dependency
        #
        handler_instance = self.router.route(message)
        message_type = self.router.classify_message(message)
        if isinstance(message_type, str):
            self.logger.bind(tag=TAG).debug("Routing to TextMessageHandler")
            try:
                await handler_instance.handle(message, self)
                self.client_abort = self.client_abort
                self.client_listen_mode = self.client_listen_mode
                self.client_have_voice = self.client_have_voice
                self.client_voice_stop = self.client_voice_stop
                # ... update other relevant states if HandlerContext modifies them
            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"Error in TextMessageHandler: {e}", exc_info=True
                )
                # Log state after copy-back
                self.logger.bind(tag=TAG).debug(
                    f"State after TextHandler copy-back: self.client_voice_stop={self.client_voice_stop}"
                )
        elif isinstance(message_type, bytes):
            self.logger.bind(tag=TAG).debug("Routing to AudioMessageHandler")
            # context = self._create_handler_context()
            try:
                await handler_instance.handle(message, self)
                self.client_abort = self.client_abort
                self.asr_server_receive = self.asr_server_receive
                self.asr_audio = list(self.asr_audio)  # Sync back the audio buffer
                # ... update other relevant states if HandlerContext modifies them
            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"Error in AudioMessageHandler: {e}", exc_info=True
                )
        elif handler_instance:
            # Handle other potential handlers if added later
            self.logger.bind(tag=TAG).warning(
                f"Routing for handler type {type(handler_instance).__name__} not fully implemented yet."
            )
        else:  # handler_instance is None
            self.logger.bind(tag=TAG).warning(
                f"Router returned None for message type: {type(message)}, cannot route."
            )

    def chat(self, query):
        try:
            if self.isNeedAuth():
                self.llm_finish_task = True
                future = asyncio.run_coroutine_threadsafe(
                    self._check_and_broadcast_auth_code(), self.loop
                )
                future.result()
                return True

            self.dialogue.put(Message(role="user", content=query))

            response_message = []
            processed_chars = 0  # 跟踪已处理的字符位置
            try:
                start_time = time.time()
                # 使用带记忆的对话
                future = asyncio.run_coroutine_threadsafe(
                    self.memory.query_memory(query), self.loop
                )
                memory_str = future.result()

                self.logger.bind(tag=TAG).debug(f"记忆内容: {memory_str}")
                llm_responses = self.llm.response(
                    self.session_id,
                    self.dialogue.get_llm_dialogue_with_memory(memory_str),
                )
            except Exception as e:
                self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
                return None

            self.llm_finish_task = False
            text_index = 0
            for content in llm_responses:
                response_message.append(content)
                if self.client_abort:
                    break

                end_time = time.time()
                # self.logger.bind(tag=TAG).debug(f"大模型返回时间: {end_time - start_time} 秒, 生成token={content}")

                # 合并当前全部文本并处理未分割部分
                full_text = "".join(response_message)
                current_text = full_text[processed_chars:]  # 从未处理的位置开始

                # 查找最后一个有效标点
                punctuations = ("。", "？", "！", "；", "：")
                last_punct_pos = -1
                for punct in punctuations:
                    pos = current_text.rfind(punct)
                    if pos > last_punct_pos:
                        last_punct_pos = pos

                # 找到分割点则处理
                if last_punct_pos != -1:
                    segment_text_raw = current_text[: last_punct_pos + 1]
                    segment_text = get_string_no_punctuation_or_emoji(segment_text_raw)
                    if segment_text:
                        # 强制设置空字符，测试TTS出错返回语音的健壮性
                        # if text_index % 2 == 0:
                        #     segment_text = " "
                        text_index += 1
                        self.logger.bind(tag=TAG).debug(
                            f"[chat] Found segment [{text_index}]: '{segment_text}'"
                        )
                        self.recode_first_last_text(segment_text, text_index)
                        try:
                            self.logger.bind(tag=TAG).debug(
                                f"[chat] Submitting TTS task for index {text_index}..."
                            )
                            future = self.executor.submit(
                                self.speak_and_play, segment_text, text_index
                            )
                            self.logger.bind(tag=TAG).debug(
                                f"[chat] Submitting future for index {text_index} to dispatcher..."
                            )
                            self.dispatcher.dispatch_tts(future)
                            self.logger.bind(tag=TAG).debug(
                                f"[chat] Dispatched TTS future for index {text_index}."
                            )
                            processed_chars += len(segment_text_raw)
                        except Exception as e:
                            self.logger.bind(tag=TAG).error(
                                f"[chat] Error submitting/dispatching TTS task for index {text_index}: {e}",
                                exc_info=True,
                            )

            # 处理最后剩余的文本
            full_text = "".join(response_message)
            remaining_text = full_text[processed_chars:]
            if remaining_text:
                segment_text = get_string_no_punctuation_or_emoji(remaining_text)
                if segment_text:
                    text_index += 1
                    self.logger.bind(tag=TAG).debug(
                        f"[chat] Found final segment [{text_index}]: '{segment_text}'"
                    )
                    self.recode_first_last_text(segment_text, text_index)
                    try:
                        self.logger.bind(tag=TAG).debug(
                            f"[chat] Submitting final TTS task for index {text_index}..."
                        )
                        future = self.executor.submit(
                            self.speak_and_play, segment_text, text_index
                        )
                        self.logger.bind(tag=TAG).debug(
                            f"[chat] Submitting final future for index {text_index} to dispatcher..."
                        )
                        self.dispatcher.dispatch_tts(future)
                        self.logger.bind(tag=TAG).debug(
                            f"[chat] Dispatched final TTS future for index {text_index}."
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(
                            f"[chat] Error submitting/dispatching final TTS task for index {text_index}: {e}",
                            exc_info=True,
                        )

            self.llm_finish_task = True
            self.dialogue.put(
                Message(role="assistant", content="".join(response_message))
            )
            self.logger.bind(tag=TAG).debug(
                json.dumps(
                    self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False
                )
            )
        except Exception as e:
            print(e)
        return True

    def chat_with_function_calling(self, query, tool_call=False):
        self.logger.bind(tag=TAG).debug(f"Chat with function calling start: {query}")
        """Chat with function calling for intent detection using streaming"""
        if self.isNeedAuth():
            self.llm_finish_task = True
            future = asyncio.run_coroutine_threadsafe(
                self._check_and_broadcast_auth_code(), self.loop
            )
            future.result()
            return True

        if not tool_call:
            self.dialogue.put(Message(role="user", content=query))

        # Define intent functions
        functions = None
        if hasattr(self, "func_handler"):
            functions = self.func_handler.get_functions()
        response_message = []
        processed_chars = 0  # 跟踪已处理的字符位置

        try:
            start_time = time.time()

            # 使用带记忆的对话
            future = asyncio.run_coroutine_threadsafe(
                self.memory.query_memory(query), self.loop
            )
            memory_str = future.result()

            # self.logger.bind(tag=TAG).info(f"对话记录: {self.dialogue.get_llm_dialogue_with_memory(memory_str)}")

            # 使用支持functions的streaming接口
            llm_responses = self.llm.response_with_functions(
                self.session_id,
                self.dialogue.get_llm_dialogue_with_memory(memory_str),
                functions=functions,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 处理出错 {query}: {e}")
            return None

        self.llm_finish_task = False
        text_index = 0

        # 处理流式响应
        tool_call_flag = False
        function_name = None
        function_id = None
        function_arguments = ""
        content_arguments = ""
        for response in llm_responses:
            content, tools_call = response
            if "content" in response:
                content = response["content"]
                tools_call = None
            if content is not None and len(content) > 0:
                if len(response_message) <= 0 and (
                    content == "```" or "<tool_call>" in content
                ):
                    tool_call_flag = True

            if tools_call is not None:
                tool_call_flag = True
                if tools_call[0].id is not None:
                    function_id = tools_call[0].id
                if tools_call[0].function.name is not None:
                    function_name = tools_call[0].function.name
                if tools_call[0].function.arguments is not None:
                    function_arguments += tools_call[0].function.arguments

            if content is not None and len(content) > 0:
                if tool_call_flag:
                    content_arguments += content
                else:
                    response_message.append(content)

                    if self.client_abort:
                        break

                    end_time = time.time()
                    self.logger.bind(tag=TAG).debug(
                        f"大模型返回时间: {end_time - start_time} 秒, 生成token={content}"
                    )

                    # 处理文本分段和TTS逻辑
                    # 合并当前全部文本并处理未分割部分
                    full_text = "".join(response_message)
                    current_text = full_text[processed_chars:]  # 从未处理的位置开始

                    # 查找最后一个有效标点
                    punctuations = ("。", "？", "！", "；", "：")
                    last_punct_pos = -1
                    for punct in punctuations:
                        pos = current_text.rfind(punct)
                        if pos > last_punct_pos:
                            last_punct_pos = pos

                    # 找到分割点则处理
                    if last_punct_pos != -1:
                        segment_text_raw = current_text[: last_punct_pos + 1]
                        segment_text = get_string_no_punctuation_or_emoji(
                            segment_text_raw
                        )
                        if segment_text:
                            text_index += 1
                            self.logger.bind(tag=TAG).debug(
                                f"[fc_chat] Found segment [{text_index}]: '{segment_text}'"
                            )
                            self.recode_first_last_text(segment_text, text_index)
                            try:
                                self.logger.bind(tag=TAG).debug(
                                    f"[fc_chat] Submitting TTS task for index {text_index}..."
                                )
                                future = self.executor.submit(
                                    self.speak_and_play, segment_text, text_index
                                )
                                self.logger.bind(tag=TAG).debug(
                                    f"[fc_chat] Submitting future for index {text_index} to dispatcher..."
                                )
                                self.dispatcher.dispatch_tts(future)
                                self.logger.bind(tag=TAG).debug(
                                    f"[fc_chat] Dispatched TTS future for index {text_index}."
                                )
                                # 更新已处理字符位置
                                processed_chars += len(segment_text_raw)
                            except Exception as e:
                                self.logger.bind(tag=TAG).error(
                                    f"[fc_chat] Error submitting/dispatching TTS task for index {text_index}: {e}",
                                    exc_info=True,
                                )

        # 处理function call
        if tool_call_flag:
            bHasError = False
            if function_id is None:
                a = extract_json_from_string(content_arguments)
                if a is not None:
                    try:
                        content_arguments_json = json.loads(a)
                        function_name = content_arguments_json["name"]
                        function_arguments = json.dumps(
                            content_arguments_json["arguments"], ensure_ascii=False
                        )
                        function_id = str(uuid.uuid4().hex)
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(f"function call error: {e}")
                        bHasError = True
                        response_message.append(a)
                else:
                    bHasError = True
                    response_message.append(content_arguments)
                if bHasError:
                    self.logger.bind(tag=TAG).error(
                        f"function call error: {content_arguments}"
                    )
                else:
                    function_arguments = json.loads(function_arguments)
            if not bHasError:
                self.logger.bind(tag=TAG).info(
                    f"function_name={function_name}, function_id={function_id}, function_arguments={function_arguments}"
                )
                function_call_data = {
                    "name": function_name,
                    "id": function_id,
                    "arguments": function_arguments,
                }

                # 处理MCP工具调用
                if self.mcp_manager.is_mcp_tool(function_name):
                    result = self._handle_mcp_tool_call(function_call_data)
                else:
                    # 处理系统函数
                    result = self.func_handler.handle_llm_function_call(
                        self, function_call_data
                    )
                self._handle_function_result(result, function_call_data, text_index + 1)

        # 处理最后剩余的文本
        full_text = "".join(response_message)
        remaining_text = full_text[processed_chars:]
        if remaining_text:
            segment_text = get_string_no_punctuation_or_emoji(remaining_text)
            if segment_text:
                text_index += 1
                self.logger.bind(tag=TAG).debug(
                    f"[fc_chat] Found final segment [{text_index}]: '{segment_text}'"
                )
                self.recode_first_last_text(segment_text, text_index)
                try:
                    self.logger.bind(tag=TAG).debug(
                        f"[fc_chat] Submitting final TTS task for index {text_index}..."
                    )
                    future = self.executor.submit(
                        self.speak_and_play, segment_text, text_index
                    )
                    self.logger.bind(tag=TAG).debug(
                        f"[fc_chat] Submitting final future for index {text_index} to dispatcher..."
                    )
                    self.dispatcher.dispatch_tts(future)
                    self.logger.bind(tag=TAG).debug(
                        f"[fc_chat] Dispatched final TTS future for index {text_index}."
                    )
                except Exception as e:
                    self.logger.bind(tag=TAG).error(
                        f"[fc_chat] Error submitting/dispatching final TTS task for index {text_index}: {e}",
                        exc_info=True,
                    )

        # 存储对话内容
        if len(response_message) > 0:
            self.dialogue.put(
                Message(role="assistant", content="".join(response_message))
            )

        self.llm_finish_task = True
        self.logger.bind(tag=TAG).debug(
            json.dumps(self.dialogue.get_llm_dialogue(), indent=4, ensure_ascii=False)
        )

        return True
