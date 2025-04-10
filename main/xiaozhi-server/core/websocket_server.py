import asyncio
import websockets
from config.logger import setup_logging
from core.connection import ConnectionHandler
from core.utils.util import get_local_ip
from core.utils import asr, vad, llm, tts, memory, intent
from typing import Dict, Any, Optional

TAG = __name__


class WebSocketServer:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging()
        self._vad, self._asr, self._llm, self._tts, self._memory, self._intent = (
            self._create_processing_instances()
        )
        self.active_connections = set()  # 添加全局连接记录

    def _get_selected_provider_config(self, provider_type: str) -> Optional[Dict[str, Any]]:
        """获取当前选定提供者的配置"""
        selected_module = self.config.get("selected_module", {})
        provider_name = selected_module.get(provider_type)
        if not provider_name:
            self.logger.bind(tag=TAG).warning(f"No provider selected for type: {provider_type}")
            return None

        provider_configs = self.config.get(provider_type)
        if not provider_configs or provider_name not in provider_configs:
            self.logger.bind(tag=TAG).warning(f"Configuration not found for {provider_type}: {provider_name}")
            return None

        return provider_configs[provider_name]

    def _get_provider_type_or_name(self, provider_type: str) -> Optional[str]:
         """获取提供者的类型（如果配置中指定）或其名称"""
         selected_config = self._get_selected_provider_config(provider_type)
         if not selected_config:
             # 如果没有找到选定提供者的配置，仍然尝试返回选定的模块名称作为后备
             return self.config.get("selected_module", {}).get(provider_type)

         # 检查配置中是否有明确的 'type' 字段
         explicit_type = selected_config.get("type")
         if explicit_type:
             return explicit_type
         else:
             # 如果没有 'type' 字段，则返回提供者的名称
             return self.config.get("selected_module", {}).get(provider_type)

    def _create_processing_instances(self):
        """创建处理模块实例"""
        # Memory 特殊处理，因为它可能没有显式配置或被命名为 'nomem'
        memory_cls_name = self.config.get("selected_module", {}).get("Memory", "nomem")
        memory_provider_configs = self.config.get("Memory", {})
        memory_cfg = memory_provider_configs.get(memory_cls_name, {})

        # 获取其他提供者的配置和类型/名称
        vad_config = self._get_selected_provider_config("VAD")
        vad_type = self._get_provider_type_or_name("VAD")

        asr_config = self._get_selected_provider_config("ASR")
        asr_type = self._get_provider_type_or_name("ASR")

        llm_config = self._get_selected_provider_config("LLM")
        llm_type = self._get_provider_type_or_name("LLM")

        tts_config = self._get_selected_provider_config("TTS")
        tts_type = self._get_provider_type_or_name("TTS")

        intent_config = self._get_selected_provider_config("Intent")
        intent_type = self._get_provider_type_or_name("Intent")

        delete_audio = self.config.get("delete_audio", False) # 获取 delete_audio 配置

        # 使用获取的配置创建实例
        # 添加检查以确保配置和类型/名称存在
        _vad = vad.create_instance(vad_type, vad_config) if vad_type and vad_config else None
        _asr = asr.create_instance(asr_type, asr_config, delete_audio) if asr_type and asr_config else None
        _llm = llm.create_instance(llm_type, llm_config) if llm_type and llm_config else None
        _tts = tts.create_instance(tts_type, tts_config, delete_audio) if tts_type and tts_config else None
        _memory = memory.create_instance(memory_cls_name, memory_cfg) # Memory 保持原有逻辑
        _intent = intent.create_instance(intent_type, intent_config) if intent_type and intent_config else None

        # 检查是否有任何实例创建失败
        modules = {"VAD": _vad, "ASR": _asr, "LLM": _llm, "TTS": _tts, "Memory": _memory, "Intent": _intent}
        failed_modules = [name for name, instance in modules.items() if instance is None]

        if failed_modules:
             self.logger.bind(tag=TAG).error(f"Failed to create the following processing instances due to missing configuration or type: {', '.join(failed_modules)}")
             # 根据需要可以决定是否抛出异常或退出
             # raise ValueError(f"Failed to create essential processing instances: {', '.join(failed_modules)}")

        return _vad, _asr, _llm, _tts, _memory, _intent

    async def start(self):
        server_config = self.config["server"]
        host = server_config["ip"]
        port = server_config["port"]

        self.logger.bind(tag=TAG).info(
            "Server is running at ws://{}:{}/xiaozhi/v1/", get_local_ip(), port
        )
        self.logger.bind(tag=TAG).info(
            "=======上面的地址是websocket协议地址，请勿用浏览器访问======="
        )
        self.logger.bind(tag=TAG).info(
            "如想测试websocket请用谷歌浏览器打开test目录下的test_page.html"
        )
        self.logger.bind(tag=TAG).info(
            "=============================================================\n"
        )
        async with websockets.serve(self._handle_connection, host, port):
            await asyncio.Future()

    async def _handle_connection(self, websocket):
        """处理新连接，每次创建独立的ConnectionHandler"""
        # 检查核心实例是否都已成功创建 (更精确地检查必需的实例)
        required_instances = [self._vad, self._asr, self._llm, self._tts, self._memory, self._intent] # 根据实际需求调整必需项
        if not all(required_instances):
             missing_names = [name for name, inst in zip(["VAD", "ASR", "LLM", "TTS", "Memory", "Intent"], required_instances) if inst is None]
             self.logger.bind(tag=TAG).error(f"Cannot handle connection: Essential processing instances are missing: {', '.join(missing_names)}")
             await websocket.close(code=1011, reason="Server configuration error.")
             return

        # 创建 ConnectionHandler 时传入当前 server 实例的实例变量
        handler = ConnectionHandler(
            self.config,
            self._vad,
            self._asr,
            self._llm,
            self._tts,
            self._memory,
            self._intent, # 传递 _intent
        )
        self.active_connections.add(handler)
        try:
            await handler.handle_connection(websocket)
        finally:
            self.active_connections.discard(handler)
