"""MCP服务管理器"""
import os
import json
from typing import Dict, Any, List
from .MCPClient import MCPClient
from config.logger import setup_logging
from core.utils.util import get_project_dir
from plugins_func.register import register_function, ToolType

TAG = __name__

class MCPManager:
    """管理多个MCP服务的集中管理器"""

    def __init__(self,context) -> None:
        """
        初始化MCP管理器
        """
        self.context = context
        self.logger = setup_logging()
        self.config_path = get_project_dir() + 'data/.mcp_server_settings.json'
        if not os.path.exists(self.config_path):
            self.config_path = ""
            self.logger.bind(tag=TAG).warning("请检查mcp服务配置文件：data/.mcp_server_settings.json")
        self.client: Dict[str, MCPClient] = {}
        self.tools = []

    def load_config(self) -> Dict[str, Any]:
        """加载MCP服务配置
        Returns:
            Dict[str, Any]: 服务配置字典
        """
        if len(self.config_path) == 0:
            return {}
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get('mcpServers', {})
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"Error loading MCP config from {self.config_path}: {e}")
            return {}

    async def initialize_servers(self) -> None:
        """初始化所有MCP服务"""
        try:
            config = self.load_config()
            for name, srv_config in config.items():
                if not srv_config.get("command"):
                    self.logger.bind(tag=TAG).warning(f"Skipping server {name}: command not specified")
                    continue

                try:
                    client = MCPClient(srv_config)
                    await client.initialize()
                    self.client[name] = client
                    self.logger.bind(tag=TAG).info(f"Initialized MCP client: {name}")
                    client_tools = client.get_available_tools()
                    self.tools.extend(client_tools)
                    for tool in client_tools:
                        func_name = "mcp_"+tool["function"]["name"]
                        register_function(func_name, tool, ToolType.MCP_CLIENT)(self.execute_tool)
                        self.context.func_handler.function_registry.register_function(func_name)

                except Exception as e:
                    self.logger.bind(tag=TAG).exception(f"Failed to initialize MCP server {name}: {e}")
            self.context.func_handler.upload_functions_desc()
        except Exception as e:
            self.logger.bind(tag=TAG).exception(f"Failed to initialize MCP servers: {e}")

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """获取所有服务的工具function定义
        Returns:
            List[Dict[str, Any]]: 所有工具的function定义列表
        """
        return self.tools

    def is_mcp_tool(self, tool_name: str) -> bool:
        """检查是否是MCP工具
        Args:
            tool_name: 工具名称
        Returns:
            bool: 是否是MCP工具
        """
        for tool in self.tools:
            if tool.get("function") is not None and tool["function"].get("name") == tool_name:
                return True
        return False

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """执行工具调用
        Args:
            tool_name: 工具名称
            arguments: 工具参数 
        Returns:
            Any: 工具执行结果
        Raises:
            ValueError: 工具未找到时抛出
        """
        self.logger.bind(tag=TAG).info(f"Executing tool {tool_name} with arguments: {arguments}")
        for client in self.client.values():
            if client.has_tool(tool_name):
                return await client.call_tool(tool_name, arguments)
            
        raise ValueError(f"Tool {tool_name} not found in any MCP server")

    async def cleanup_all(self) -> None:
        for name, client in self.client.items():
            try:
                await client.cleanup()
                self.logger.bind(tag=TAG).info(f"Cleaned up MCP client: {name}")
            except Exception as e:
                self.logger.bind(tag=TAG).exception(f"Error cleaning up MCP client {name}: {e}")
        self.client.clear()
