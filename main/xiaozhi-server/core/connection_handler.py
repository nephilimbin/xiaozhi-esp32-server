import uuid
import queue
import asyncio
import traceback
from typing import Dict, Any, Optional

import threading
import websockets
from plugins_func.loadplugins import auto_import_modules
from config.logger import setup_logging
from core.utils.dialogue import Message, Dialogue
from core.utils.util import get_ip_info
from core.channels.interface import ICommunicationChannel
from core.channels.websocket import WebSocketChannel
from concurrent.futures import ThreadPoolExecutor
from core.auth import AuthMiddleware, AuthenticationError
from core.utils.auth_code_gen import AuthCodeGenerator
from core.connection.state import StateManager
from core.connection.tasks import TaskDispatcher
from core.message_handlers.context import HandlerContext


TAG = __name__

auto_import_modules("plugins_func.functions")

class TTSException(RuntimeError):
    pass


class ConnectionHandler:
    def __init__(
        self,
        websocket: 'WebSocketChannel',
        config: Dict[str, Any],
        vad,
        asr,
        llm,
        tts,
        memory,
        intent,
    ):
        # 依赖的组件
        self.vad = vad
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.memory = memory
        self.intent = intent

        # 全局变量
        self.config = config
        self.websocket = websocket
        self.logger = setup_logging()
        self.channel: Optional[ICommunicationChannel] = None
        self.auth = AuthMiddleware(config)
        self.headers = None  # 私有属性，装在client_ip_info
        self.client_ip = None  # 私有属性，包装在client_ip_info
        self.client_ip_info = {}
        self.session_id = None
        self.prompt = None
        self.welcome_msg = None

        # 线程任务相关
        self.loop = asyncio.get_event_loop()
        self.stop_event = threading.Event()
        self.tts_queue = queue.Queue()
        self.audio_play_queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=10)

        # 任务调度器
        self.dispatcher = TaskDispatcher(
            self.loop, self.executor, self.tts_queue, self.audio_play_queue
        )
        self._state_manager = StateManager()  # 状态管理器, 私有属性
        
        # llm相关变量
        self.llm_finish_task = False
        self.dialogue = Dialogue()
        self.close_after_chat = False  # 是否在聊天结束后关闭连接,暂时程序未用到

        # 私有配置相关变量
        self.private_config = None
        self.auth_code_gen = AuthCodeGenerator.get_instance()
        self.is_device_verified = False  # 添加设备验证状态标志


    def _create_handler_context(self) -> "HandlerContext":
        """Creates and populates the HandlerContext for message handlers."""
        # Ensure all required fields for HandlerContext are sourced from self
        # Note: This assumes HandlerContext definition matches the attributes available in ConnectionHandler (self)
        self.contexter = HandlerContext(
            vad=self.vad,
            asr=self.asr,
            llm=self.llm,
            tts=self.tts,
            memory=self.memory,
            intent=self.intent,
            config=self.config,
            websocket=self.websocket,
            logger=self.logger,
            channel=self.channel,
            client_ip_info=self.client_ip_info,
            session_id=self.session_id,
            prompt=self.prompt,
            welcome_msg=self.welcome_msg,
            loop=self.loop,
            stop_event=self.stop_event,
            tts_queue=self.tts_queue,
            audio_play_queue=self.audio_play_queue,
            executor=self.executor,
            dispatcher=self.dispatcher,
            llm_finish_task=self.llm_finish_task,
            dialogue=self.dialogue,
            close_after_chat=self.close_after_chat,
        )  
        return self.contexter

    async def handle_connection(self):
        try:
            # 获取并验证headers
            self.headers = dict(self.websocket.request.headers)
            # 获取客户端ip地址
            self.client_ip = self.websocket.remote_address[0]
            self.logger.bind(tag=TAG).info(f"{self.client_ip} conn - Headers: {self.headers}")

            # 登陆进行认证
            await self.auth.start_authenticate(self.headers)
            device_id = self.headers.get("device-id", None)

            # 认证通过,继续处理
            self.session_id = str(uuid.uuid4())
            self.channel = WebSocketChannel(self.websocket)

            self.welcome_msg = self.config["xiaozhi"]
            self.welcome_msg["session_id"] = self.session_id
            await self.channel.send_message(self.welcome_msg)

            # Load private configuration using StateManager
            (
                self.private_config,
                self.is_device_verified,
            ) = await self._state_manager.load_private_config(
                self.headers, self.config, self.auth_code_gen
            )
            # 如果私有配置存在，则检查设备绑定状态
            if self.private_config:
                self.llm_finish_task = True # TODO 该参数没有实际作用，考虑是否删除。
                future = asyncio.run_coroutine_threadsafe(
                    self._check_and_broadcast_auth_code(), self.loop
                )
                future.result()
            # If private config was loaded, check for private LLM/TTS instances and update last chat time
            if self.private_config:
                if self.is_device_verified:
                    # Update chat time only if device is verified
                    await self.private_config.update_last_chat_time()

                # Try creating private instances and update if successful
                private_llm, private_tts = (
                    self.private_config.create_private_instances()
                )
                if all([private_llm, private_tts]):
                    self.llm = private_llm
                    self.tts = private_tts
                    self.logger.bind(tag=TAG).info(
                        f"Loaded private config and instances for device {self.private_config.device_id}"
                    )
                else:
                    self.logger.bind(tag=TAG).error(
                        f"Failed to create private LLM/TTS instances for device {self.private_config.device_id}, using defaults."
                    )

            # 异步初始化 - 使用 TaskDispatcher
            self.dispatcher.dispatch_plugin_task(self._initialize_components)

            ###################### 创建contexter，接管消息处理 ######################
            future = self.dispatcher.dispatch_plugin_task(self._create_handler_context)
            # 等待线程完成
            future.result()

            # tts 消化线程
            self.tts_priority_thread = threading.Thread(
                target=self.contexter._tts_priority_thread, daemon=True
            )
            self.tts_priority_thread.start()

            # 音频播放 消化线程
            self.audio_play_priority_thread = threading.Thread(
                target=self.contexter._audio_play_priority_thread, daemon=True
            )
            self.audio_play_priority_thread.start()

            try:
                async for message in self.websocket:
                    await self.contexter._route_message(message)
            except websockets.exceptions.ConnectionClosed:
                self.logger.bind(tag=TAG).info("客户端断开连接")

        except AuthenticationError as e:
            self.logger.bind(tag=TAG).error(f"Authentication failed: {str(e)}")
            return
        except Exception as e:
            stack_trace = traceback.format_exc()
            self.logger.bind(tag=TAG).error(f"Connection error: {str(e)}-{stack_trace}")
            return
        finally:
            await self._save_and_close(self.websocket)

    async def _save_and_close(self, ws):
        """保存记忆并关闭连接"""
        try:
            # Use StateManager to save memory
            await self._state_manager.save_memory(self.memory, self.dialogue.dialogue)
        except Exception as e:
            # Logging is now handled within save_memory, but keep high-level log
            self.logger.bind(tag=TAG).error(f"Error during save and close process: {e}")
        finally:
            await self.close(ws)

    def _initialize_components(self):
        """加载提示词"""
        self.prompt = self.config["prompt"]
        if self.private_config:
            self.prompt = self.private_config.private_config.get("prompt", self.prompt)
        self.dialogue.put(Message(role="system", content=self.prompt))
        self.logger.bind(tag=TAG).info(f"系统提示词: {self.prompt}")

        """加载记忆"""
        self._initialize_memory()
        """加载意图识别"""
        self._initialize_intent()
        """加载位置信息"""
        self.client_ip_info = get_ip_info(self.client_ip)
        if self.client_ip_info is not None and "city" in self.client_ip_info:
            self.logger.bind(tag=TAG).info(f"Client ip info: {self.client_ip_info}")
            self.prompt = self.prompt + f"\nuser location:{self.client_ip_info}"

            self.dialogue.update_system_message(self.prompt)

    def _initialize_memory(self):
        """初始化记忆模块"""
        device_id = self.headers.get("device-id", None)
        self.memory.init_memory(device_id, self.llm)

    def _initialize_intent(self):
        """初始化意图识别模块"""
        # 获取意图识别配置
        intent_config = self.config["Intent"]
        intent_type = self.config["selected_module"]["Intent"]

        # 如果使用 nointent，直接返回
        if intent_type == "nointent":
            return
        # 使用 intent_llm 模式
        elif intent_type == "intent_llm":
            intent_llm_name = intent_config["intent_llm"]["llm"]

            if intent_llm_name and intent_llm_name in self.config["LLM"]:
                # 如果配置了专用LLM，则创建独立的LLM实例
                from core.utils import llm as llm_utils

                intent_llm_config = self.config["LLM"][intent_llm_name]
                intent_llm_type = intent_llm_config.get("type", intent_llm_name)
                intent_llm = llm_utils.create_instance(
                    intent_llm_type, intent_llm_config
                )
                self.logger.bind(tag=TAG).info(
                    f"为意图识别创建了专用LLM: {intent_llm_name}, 类型: {intent_llm_type}"
                )
                self.intent.set_llm(intent_llm)
            else:
                # 否则使用主LLM
                self.intent.set_llm(self.llm)
                self.logger.bind(tag=TAG).info("使用主LLM作为意图识别模型")


    def change_system_prompt(self, prompt):
        self.prompt = prompt
        # 找到原来的role==system，替换原来的系统提示
        for m in self.dialogue.dialogue:
            if m.role == "system":
                m.content = prompt


    async def _check_and_broadcast_auth_code(self):
        """检查设备绑定状态并广播认证码"""
        # TODO 【验证逻辑混乱】后续需重构
        if not self.private_config.get_owner():
            auth_code = self.private_config.get_auth_code()
            if auth_code:
                # 发送验证码语音提示
                text = f"请在后台输入验证码：{' '.join(auth_code)}"
                self.recode_first_last_text(text)
                future = self.executor.submit(self.contexter.speak_and_play, text)
                self.dispatcher.dispatch_tts(future)
            return False
        return True



    async def close(self, ws=None):
        """资源清理方法"""
        # 清理MCP资源
        try:
            if hasattr(self.contexter, "mcp_manager") and self.contexter.mcp_manager:
                await self.contexter.mcp_manager.cleanup_all()

            # 触发停止事件并清理资源    
            if self.stop_event:
                self.stop_event.set()

            # 立即关闭线程池
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            # 清空任务队列
            self._clear_queues()

            if ws:
                await ws.close()
            elif self.websocket:
                await self.websocket.close()
            self.logger.bind(tag=TAG).info("连接资源已释放")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"关闭连接时出错: {e}")

    def _clear_queues(self):
        # 清空所有任务队列
        for q in [self.contexter.tts_queue, self.contexter.audio_play_queue]:
            if not q:
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    continue
            q.queue.clear()
            # 添加毒丸信号到队列，确保线程退出
            # q.queue.put(None)


    # TODO 关联SendAudioHandler 暂时未用到
    # def chat_and_close(self, text):
    #     """Chat with the user and then close the connection"""
    #     try:
    #         # Use the existing chat method
    #         self.chat(text)

    #         # After chat is complete, close the connection
    #         self.close_after_chat = True
    #     except Exception as e:
    #         self.logger.bind(tag=TAG).error(f"Chat and close error: {str(e)}")

    