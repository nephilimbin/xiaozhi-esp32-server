from dataclasses import dataclass, field
from typing import Any, List, Dict
import queue
import os
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
from plugins_func.register import Action, ActionResponse
from core.handle.functionHandler import FunctionHandler
from core.mcp.manager import MCPManager
from core.message_handlers.text import TextMessageHandler
from core.message_handlers.audio import AudioMessageHandler
from core.message_handlers.router import MessageRouter 
from core.handle.sendAudioHandler import sendAudioMessage

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
    router: MessageRouter = field(default_factory=MessageRouter)  # 消息路由器

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
    
    # 函数调用相关变量
    func_handler: Any = field(default=None)
    use_function_call_mode: bool = field(default=False)
    mcp_manager: Any = field(default=None)
    
    # 退出命令相关变量
    cmd_exit: Any = field(default=None)
    max_cmd_length: int = field(default=0)
    close_after_chat: bool = field(default=False)  # 是否在聊天结束后关闭连接,暂时程序未用到

    def __post_init__(self):

        # 初始化退出命令相关变量
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
        
        """加载插件"""
        self.func_handler = FunctionHandler(self)
        self.use_function_call_mode = (
            False
            if self.config["selected_module"]["Intent"] != "function_call"
            else True
        )
        """加载MCP工具"""
        self.mcp_manager = MCPManager(self) # 依赖func_handler，所以需要先初始化func_handler
        asyncio.run_coroutine_threadsafe(
            self.mcp_manager.initialize_servers(), self.loop
        )
        # 设置TTS输出格式
        self.tts_output_format = self.config.get("tts_output_format", "opus_stream")
        
    def reset_vad_states(self):
        self.client_audio_buffer = bytearray()
        self.client_have_voice = False
        self.client_have_voice_last_time = 0
        self.client_voice_stop = False
        self.logger.bind(tag=TAG).debug("VAD states reset.")

    async def _route_message(self, message):
        try:
            handler_instance = self.router.route(message)
            # message_type = self.router.classify_message(message)
            # if isinstance(message_type, str):
            if isinstance(handler_instance, TextMessageHandler):
                self.logger.bind(tag=TAG).debug("Routing to TextMessageHandler")
                try:
                    await handler_instance.handle(message, self)
                    self.client_abort = self.client_abort
                    self.client_listen_mode = self.client_listen_mode
                    self.client_have_voice = self.client_have_voice
                    self.client_voice_stop = self.client_voice_stop
                except Exception as e:
                    self.logger.bind(tag=TAG).error(
                        f"Error in TextMessageHandler: {e}", exc_info=True
                    )
                    self.logger.bind(tag=TAG).debug(
                        f"State after TextHandler copy-back: self.client_voice_stop={self.client_voice_stop}"
                    )
            elif isinstance(handler_instance, AudioMessageHandler):
            # elif isinstance(message_type, bytes):
                self.logger.bind(tag=TAG).debug("Routing to AudioMessageHandler")
                try:
                    await handler_instance.handle(message, self)
                    self.client_abort = self.client_abort
                    self.asr_server_receive = self.asr_server_receive
                    self.asr_audio = list(self.asr_audio) 
                except Exception as e:
                    self.logger.bind(tag=TAG).error(
                        f"Error in AudioMessageHandler: {e}", exc_info=True
                    )
            # elif handler_instance:
            #     # Handle other potential handlers if added later
            #     self.logger.bind(tag=TAG).warning(
            #         f"Routing for handler type {type(handler_instance).__name__} not fully implemented yet."
            #     )
            else:  # handler_instance is None
                self.logger.bind(tag=TAG).warning(
                    f"Router returned None for message type: {type(message)}, cannot route."
                )
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Error in context._route_message: {e}", exc_info=True)

    def chat(self, query):
        try:

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
                self.logger.bind(tag=TAG).debug(f"大模型返回时间: {end_time - start_time} 秒, 生成token={content}")

                # 合并当前全部文本并处理未分割部分
                full_text = "".join(response_message)
                current_text = full_text[processed_chars:]  # 从未处理的位置开始

                # 查找最后一个有效标点
                punctuations = ("。", "？", "！", "；", "：", ".")
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

        try:
            if not tool_call:
                self.dialogue.put(Message(role="user", content=query))
                self.logger.bind(tag=TAG).debug(f"Chat with function calling(True) start: {query}")

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

                self.logger.bind(tag=TAG).info(f"Chat with function calling 对话记录: {self.dialogue.get_llm_dialogue_with_memory(memory_str)}")

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
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"【Context】function calling error: {e}")
            return None

        return True

    def recode_first_last_text(self, text, text_index=0):
        if self.tts_first_text_index == -1:
            self.logger.bind(tag=TAG).info(f"大模型说出第一句话: {text}")
            self.tts_first_text_index = text_index
        self.tts_last_text_index = text_index

    def _handle_mcp_tool_call(self, function_call_data):
        function_arguments = function_call_data["arguments"]
        function_name = function_call_data["name"]
        try:
            args_dict = function_arguments
            if isinstance(function_arguments, str):
                try:
                    args_dict = json.loads(function_arguments)
                except json.JSONDecodeError:
                    self.logger.bind(tag=TAG).error(
                        f"无法解析 function_arguments: {function_arguments}"
                    )
                    return ActionResponse(
                        action=Action.REQLLM, result="参数解析失败", response=""
                    )

            tool_result = asyncio.run_coroutine_threadsafe(
                self.mcp_manager.execute_tool(function_name, args_dict), self.loop
            ).result()
            # meta=None content=[TextContent(type='text', text='北京当前天气:\n温度: 21°C\n天气: 晴\n湿度: 6%\n风向: 西北 风\n风力等级: 5级', annotations=None)] isError=False
            content_text = ""
            if tool_result is not None and tool_result.content is not None:
                for content in tool_result.content:
                    content_type = content.type
                    if content_type == "text":
                        content_text = content.text
                    elif content_type == "image":
                        pass

            if len(content_text) > 0:
                return ActionResponse(
                    action=Action.REQLLM, result=content_text, response=""
                )

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"MCP工具调用错误: {e}")
            return ActionResponse(
                action=Action.REQLLM, result="工具调用出错", response=""
            )

        return ActionResponse(action=Action.REQLLM, result="工具调用出错", response="")

    def _handle_function_result(self, result, function_call_data, text_index):
        if result.action == Action.RESPONSE:  # 直接回复前端
            text = result.response
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index)
            self.dispatcher.dispatch_tts(future)
            self.dialogue.put(Message(role="assistant", content=text))
        elif result.action == Action.REQLLM:  # 调用函数后再请求llm生成回复
            text = result.result
            if text is not None and len(text) > 0:
                function_id = function_call_data["id"]
                function_name = function_call_data["name"]
                function_arguments = function_call_data["arguments"]
                self.dialogue.put(
                    Message(
                        role="assistant",
                        tool_calls=[
                            {
                                "id": function_id,
                                "function": {
                                    "arguments": function_arguments,
                                    "name": function_name,
                                },
                                "type": "function",
                                "index": 0,
                            }
                        ],
                    )
                )

                self.dialogue.put(
                    Message(role="tool", tool_call_id=function_id, content=text)
                )
                self.chat_with_function_calling(text, tool_call=True)
        elif result.action == Action.NOTFOUND:
            text = result.result
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index)
            self.dispatcher.dispatch_tts(future)
            self.dialogue.put(Message(role="assistant", content=text))
        else:
            text = result.result
            self.recode_first_last_text(text, text_index)
            future = self.executor.submit(self.speak_and_play, text, text_index)
            self.dispatcher.dispatch_tts(future)
            self.dialogue.put(Message(role="assistant", content=text))

    def speak_and_play(self, text, text_index=0):
        if text is None or len(text) <= 0:
            self.logger.bind(tag=TAG).info(f"无需tts转换，query为空，{text}")
            return None, text, text_index

        tts_file = None
        max_retries = self.config.get(
            "tts_max_retries", 2
        )  # Default to 2 retries (3 attempts total)
        retry_delay = self.config.get(
            "tts_retry_delay_seconds", 0.5
        )  # Default to 0.5 seconds

        for attempt in range(max_retries + 1):
            try:
                self.logger.bind(tag=TAG).debug(
                    f"[speak_and_play] Attempt {attempt + 1}/{max_retries + 1} for TTS index {text_index}..."
                )
                tts_file = self.tts.to_tts(text)
                if tts_file is not None:
                    self.logger.bind(tag=TAG).debug(
                        f"[speak_and_play] TTS success on attempt {attempt + 1} for index {text_index}: {tts_file}"
                    )
                    break  # Success, exit loop
                else:
                    # Handle case where to_tts returns None without raising an exception (might indicate non-retryable issue)
                    self.logger.bind(tag=TAG).error(
                        f"[speak_and_play] TTS attempt {attempt + 1} returned None for index {text_index}, text: '{text}'"
                    )
                    if attempt >= max_retries:
                        self.logger.bind(tag=TAG).error(
                            f"[speak_and_play] TTS failed after {max_retries + 1} attempts for index {text_index}, returning None."
                        )
                        return (
                            None,
                            text,
                            text_index,
                        )  # Return None after all retries if to_tts consistently returns None

            except Exception as e:
                self.logger.bind(tag=TAG).error(
                    f"[speak_and_play] TTS attempt {attempt + 1} failed for index {text_index} with error: {e}",
                    exc_info=True,
                )
                if attempt >= max_retries:
                    self.logger.bind(tag=TAG).error(
                        f"[speak_and_play] TTS failed after {max_retries + 1} attempts for index {text_index}, returning None."
                    )
                    return None, text, text_index  # Return None after all retries

            # If not the last attempt, wait before retrying
            if attempt < max_retries:
                self.logger.bind(tag=TAG).warning(
                    f"[speak_and_play] Waiting {retry_delay}s before retrying TTS for index {text_index}..."
                )
                time.sleep(retry_delay)

        # If loop finished, tts_file should hold the successful result or None if all attempts failed
        if tts_file is None:
            self.logger.bind(tag=TAG).error(
                f"[speak_and_play] All TTS attempts failed for index {text_index}, returning None file path."
            )
            # Return None for the file path but keep text and index
            return None, text, text_index

        self.logger.bind(tag=TAG).debug(f"TTS 文件生成完毕: {tts_file}")
        return tts_file, text, text_index
    
    
    def _tts_priority_thread(self):
        while not self.stop_event.is_set():
            text = None
            tts_file = None
            text_index = 0
            try:
                try:
                    future = self.tts_queue.get(timeout=1)
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue
                if future is None:
                    continue

                try:
                    self.logger.bind(tag=TAG).debug("正在处理TTS任务...")
                    tts_timeout = self.config.get("tts_timeout", 10)
                    # speak_and_play returns (tts_file, text, text_index)
                    tts_file, text, text_index = future.result(timeout=tts_timeout)

                    if text is None or len(text) <= 0:
                        self.logger.bind(tag=TAG).error(
                            f"TTS出错：{text_index}: tts text is empty"
                        )
                        continue  # Skip further processing for this item
                    if tts_file is None or not os.path.exists(tts_file):
                        self.logger.bind(tag=TAG).error(
                            f"TTS出错：文件不存在或为空: {tts_file} for text index {text_index}: {text}"
                        )
                        continue  # Skip further processing for this item

                    self.logger.bind(tag=TAG).debug(
                        f"TTS生成完毕：文件路径: {tts_file}, 索引: {text_index}"
                    )

                    # --- MP3/Opus Handling Logic ---
                    if self.tts_output_format == "mp3_file":
                        # --- MP3 File Handling (Keep As Is) ---
                        self.logger.bind(tag=TAG).debug(
                            f"配置为发送MP3文件，准备读取: {tts_file}"
                        )
                        try:
                            self.logger.bind(tag=TAG).debug(
                                f"尝试读取 MP3 文件: {tts_file}"
                            )
                            with open(tts_file, "rb") as f:
                                mp3_data = f.read()
                            self.logger.bind(tag=TAG).debug(
                                f"MP3 文件读取成功, 大小: {len(mp3_data)} bytes"
                            )
                            if not self.client_abort:
                                self.logger.bind(tag=TAG).debug(
                                    f"准备将 MP3 数据放入播放队列, 索引: {text_index}"
                                )
                                self.dispatcher.dispatch_audio(
                                    (mp3_data, text, text_index, "mp3")
                                )
                                self.logger.bind(tag=TAG).debug(
                                    f"MP3数据已放入播放队列, 索引: {text_index}, 队列大小: {self.audio_play_queue.qsize()}"
                                )
                            else:
                                self.logger.bind(tag=TAG).info(
                                    f"客户端已中断，跳过发送MP3数据, 索引: {text_index}"
                                )
                        except Exception as e:
                            self.logger.bind(tag=TAG).error(
                                f"读取MP3文件失败 {tts_file}: {e}"
                            )
                        # --- End MP3 File Handling ---

                    # Default to opus_stream if format is 'opus_stream' or unknown/not 'mp3_file'
                    elif self.tts_output_format == "opus_stream":
                        # --- Opus Stream Handling (Modify to match connection.py) ---
                        self.logger.bind(tag=TAG).warning(
                                f"tts_output_format 配置: {self.tts_output_format}, 使用 opus_stream 处理"
                            )
                        self.logger.bind(tag=TAG).debug(
                            f"配置为发送Opus流，准备转换: {tts_file}"
                        )
                        try:
                            opus_datas, duration = self.tts.audio_to_opus_data(tts_file)
                            if opus_datas:
                                self.logger.bind(tag=TAG).debug(
                                    f"Opus转换成功，得到 {len(opus_datas)} 个数据包"
                                )
                                if not self.client_abort:
                                    self.logger.bind(tag=TAG).debug(
                                        f"准备将 Opus 数据包列表放入播放队列, 索引: {text_index}"
                                    )
                                    # Put the LIST of opus packets into the queue
                                    self.dispatcher.dispatch_audio(
                                        (opus_datas, text, text_index, "opus")
                                    )
                                    self.logger.bind(tag=TAG).debug(
                                        f"Opus 数据包列表已放入播放队列, 索引: {text_index}, 队列大小: {self.audio_play_queue.qsize()}"
                                    )
                                else:
                                    self.logger.bind(tag=TAG).info(
                                        f"客户端已中断，跳过发送 Opus 数据, 索引: {text_index}"
                                    )
                            else:
                                self.logger.bind(tag=TAG).error(
                                    f"Opus转换失败或返回空数据包列表: {tts_file}"
                                )
                        except Exception as e:
                            self.logger.bind(tag=TAG).error(
                                f"Opus转换失败 {tts_file}: {e}", exc_info=True
                            )
                        # --- End Opus Stream Handling ---
                    # --- End of MP3/Opus Handling Logic ---

                except TimeoutError:
                    self.logger.bind(tag=TAG).error(f"TTS任务超时, 索引: {text_index}")
                except Exception as e:
                    self.logger.bind(tag=TAG).error(
                        f"TTS任务内部处理错误, 索引: {text_index}: {e}"
                    )

            except Exception as e:
                # Error getting future or outer processing
                self.logger.bind(tag=TAG).error(f"TTS任务获取或外部处理错误: {e}")
                # Ensure state is cleared on error
                self.clearSpeakStatus()
                if self.channel:
                    asyncio.run_coroutine_threadsafe(
                        self.channel.send_message(
                            {
                                "type": "tts",  # Keep original type for general stop
                                "state": "stop",
                                "session_id": self.session_id,
                            }
                        ),
                        self.loop,
                    )
            finally:
                # --- File Deletion Logic (Ensured to run) ---
                # Delete the file after processing, regardless of format, if configured
                if tts_file and self.tts.delete_audio_file and os.path.exists(tts_file):
                    try:
                        os.remove(tts_file)
                        self.logger.bind(tag=TAG).debug(
                            f"已删除TTS临时文件: {tts_file}"
                        )
                    except Exception as e:
                        self.logger.bind(tag=TAG).error(
                            f"删除TTS文件失败 {tts_file}: {e}"
                        )
                # --- End of File Deletion Logic ---

    def _audio_play_priority_thread(self):
        while not self.stop_event.is_set():
            text = None
            audio_type = "unknown"
            text_index = 0  # Initialize text_index
            try:
                try:
                    # 从队列中获取数据
                    data, text, text_index, audio_type = self.audio_play_queue.get(
                        timeout=1
                    )
                    self.logger.bind(tag=TAG).debug(
                        f"音频播放线程成功获取到数据, 类型: {audio_type}, 索引: {text_index}"
                    )
                except queue.Empty:
                    if self.stop_event.is_set():
                        break
                    continue

                if not self.channel:
                    self.logger.bind(tag=TAG).warning(
                        "音频播放线程: 通信通道未就绪，跳过发送"
                    )
                    continue

                # --- Audio Type Handling ---
                if audio_type == "opus":
                    # --- Send Opus Stream (Now receives a LIST of packets) ---
                    opus_packet_list = data  # 'data' is now the list of opus packets
                    packet_count = (
                        len(opus_packet_list)
                        if isinstance(opus_packet_list, list)
                        else "N/A (不是列表)"
                    )
                    self.logger.bind(tag=TAG).debug(
                        f"发送Opus流 (包列表), 索引: {text_index}, 包数量: {packet_count}"
                    )
                    # sendAudioMessage 应该处理流式发送
                    future = asyncio.run_coroutine_threadsafe(
                        sendAudioMessage(self, opus_packet_list, text, text_index),
                        self.loop,
                    )
                    try:
                        future.result(timeout=30)  # 添加超时等待
                        self.logger.bind(tag=TAG).debug(
                            f"Opus流发送完成 (sendAudioMessage returned), 索引: {text_index}"
                        )
                    except TimeoutError:
                        self.logger.bind(tag=TAG).error(
                            f"sendAudioMessage for Opus stream timed out, 索引: {text_index}"
                        )
                        if not future.done():
                            future.cancel()
                    except Exception as send_exc:
                        self.logger.bind(tag=TAG).error(
                            f"sendAudioMessage for Opus stream failed, 索引: {text_index}: {send_exc}",
                            exc_info=True,
                        )

                elif audio_type == "mp3":
                    # --- Send MP3 File (Keep As Is) ---
                    mp3_binary_data = data  # data is the mp3 bytes
                    self.logger.bind(tag=TAG).debug(
                        f"准备发送MP3文件, 索引: {text_index}, 大小: {len(mp3_binary_data)} bytes"
                    )

                    start_msg = {
                        "type": "tts_mp3",
                        "state": "start",
                        "text": text,
                        "session_id": self.session_id,
                        "index": text_index,  # Include index for client tracking
                    }
                    end_msg = {
                        "type": "tts_mp3",
                        "state": "end",
                        "session_id": self.session_id,
                        "index": text_index,
                    }

                    try:
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] Scheduling sends..."
                        )
                        # Schedule start message
                        start_future = asyncio.run_coroutine_threadsafe(
                            self.channel.send_message(start_msg), self.loop
                        )
                        # Schedule binary data
                        time.sleep(0.01)
                        binary_future = asyncio.run_coroutine_threadsafe(
                            self.channel.send_bytes(mp3_binary_data), self.loop
                        )
                        # Schedule end message
                        time.sleep(0.01)
                        end_future = asyncio.run_coroutine_threadsafe(
                            self.channel.send_message(end_msg), self.loop
                        )
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] Sends scheduled. Waiting for results..."
                        )

                        start_future.result(timeout=5)
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] Start signal future completed."
                        )
                        binary_future.result(timeout=10)
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] Binary data future completed."
                        )
                        end_future.result(timeout=5)
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] End signal future completed."
                        )
                        self.logger.bind(tag=TAG).debug(
                            f"[MP3 Send {text_index}] All MP3 sends completed successfully."
                        )

                    except TimeoutError as e:
                        self.logger.bind(tag=TAG).error(
                            f"[MP3 Send {text_index}] Timeout waiting for send future: {e}"
                        )
                        if "start_future" in locals() and not start_future.done():
                            start_future.cancel()
                        if "binary_future" in locals() and not binary_future.done():
                            binary_future.cancel()
                        if "end_future" in locals() and not end_future.done():
                            end_future.cancel()
                    except Exception as send_e:
                        self.logger.bind(tag=TAG).error(
                            f"[MP3 Send {text_index}] Error during MP3 send sequence: {send_e}"
                        )
                        if "start_future" in locals() and not start_future.done():
                            start_future.cancel()
                        if "binary_future" in locals() and not binary_future.done():
                            binary_future.cancel()
                        if "end_future" in locals() and not end_future.done():
                            end_future.cancel()
                    # --- End MP3 File Handling ---

                # elif audio_type == "opus_blob":
                #     # --- Send Opus Blob (Keep As Is, although likely unused by test_page.html) ---
                #     opus_blob_data = (
                #         data  # data is the blob with length-prefixed packets
                #     )
                #     self.logger.bind(tag=TAG).debug(
                #         f"准备发送带长度信息的Opus Blob, 索引: {text_index}, 大小: {len(opus_blob_data)} bytes"
                #     )

                #     start_msg = {
                #         "type": "tts_opus_blob",  # New type
                #         "state": "start",
                #         "text": text,
                #         "session_id": self.session_id,
                #         "index": text_index,
                #     }
                #     end_msg = {
                #         "type": "tts_opus_blob",  # New type
                #         "state": "end",
                #         "session_id": self.session_id,
                #         "index": text_index,
                #     }

                #     try:
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] Scheduling sends..."
                #         )
                #         # Schedule start message
                #         start_future = asyncio.run_coroutine_threadsafe(
                #             self.channel.send_message(start_msg), self.loop
                #         )
                #         # Schedule binary data (Opus Blob)
                #         time.sleep(0.01)
                #         binary_future = asyncio.run_coroutine_threadsafe(
                #             self.channel.send_bytes(opus_blob_data), self.loop
                #         )
                #         # Schedule end message
                #         time.sleep(0.01)
                #         end_future = asyncio.run_coroutine_threadsafe(
                #             self.channel.send_message(end_msg), self.loop
                #         )
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] Sends scheduled. Waiting for results..."
                #         )

                #         start_future.result(timeout=5)
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] Start signal future completed."
                #         )
                #         binary_future.result(timeout=10)
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] Binary data future completed."
                #         )
                #         end_future.result(timeout=5)
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] End signal future completed."
                #         )
                #         self.logger.bind(tag=TAG).debug(
                #             f"[OpusBlob Send {text_index}] All Opus Blob sends completed successfully."
                #         )

                #     except TimeoutError as e:
                #         self.logger.bind(tag=TAG).error(
                #             f"[OpusBlob Send {text_index}] Timeout waiting for send future: {e}"
                #         )
                #         if "start_future" in locals() and not start_future.done():
                #             start_future.cancel()
                #         if "binary_future" in locals() and not binary_future.done():
                #             binary_future.cancel()
                #         if "end_future" in locals() and not end_future.done():
                #             end_future.cancel()
                #     except Exception as send_e:
                #         self.logger.bind(tag=TAG).error(
                #             f"[OpusBlob Send {text_index}] Error during Opus Blob send sequence: {send_e}"
                #         )
                #         if "start_future" in locals() and not start_future.done():
                #             start_future.cancel()
                #         if "binary_future" in locals() and not binary_future.done():
                #             binary_future.cancel()
                #         if "end_future" in locals() and not end_future.done():
                #             end_future.cancel()
                #     # --- End Opus Blob Handling ---

                else:
                    self.logger.bind(tag=TAG).error(
                        f"音频播放队列中收到未知类型: {audio_type}, 索引: {text_index}"
                    )
                # --- End Audio Type Handling ---

            except Exception as e:
                # Log general errors in the thread loop
                self.logger.bind(tag=TAG).error(
                    f"音频播放线程出错 (类型: {audio_type}, 索引: {text_index}, 文本: {text}): {e}"
                )
                # Consider potential cleanup or state reset needed here
                
    def clearSpeakStatus(self):
        self.logger.bind(tag=TAG).debug("清除服务端讲话状态")
        self.asr_server_receive = True
        self.tts_last_text_index = -1
        self.tts_first_text_index = -1