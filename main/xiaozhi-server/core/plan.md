第 0 步：准备工作
- 备份： 为你当前可工作的代码创建备份或提交（commit）。
- 测试： 确保你可以轻松启动服务器并测试基本的连接、消息发送/接收，理想情况下还包括 TTS/音频播放功能。

第 1 步：创建新文件和空类 (**已完成**)
1.  `core/connection/manager.py` (包含 `class ConnectionManager:`) - **已创建**
2.  `core/connection/state.py` (包含 `class StateManager:`) - **已创建**
3.  `core/connection/tasks.py` (包含 `class TaskDispatcher:`) - **已创建**
4.  `core/auth.py` (已存在 `AuthMiddleware`，将使用它代替创建`Authenticator`) - **已存在**
5.  `core/routing.py` (包含 `class MessageRouter:`) - **已创建**
6.  `core/message_handlers/base.py` (包含 `BaseMessageHandler` 抽象类) - **已创建**
7.  `core/message_handlers/text.py` (包含 `TextMessageHandler`) - **已创建**
8.  `core/message_handlers/audio.py` (包含 `AudioMessageHandler`) - **已创建**
9.  `core/channels/websocket_wrapper.py` (包含 `class WebSocketWrapper:`) - **已确认存在** (但请看下面第 2 步的讨论)
10. `core/message_handlers/context.py` (包含 `HandlerContext`) - **已创建**
- 理由： 建立目标文件结构，同时不破坏任何现有功能。
- 测试： 启动服务器。它应该和之前完全一样运行，因为没有逻辑被改变。

第 2 步：使用 WebSocketChannel 替换发送调用 (调整后方案) - **已完成**
- **目标**: 将 `core/connection.py` 中对底层 `websocket.send()` 的直接调用，替换为通过你现有的 `core/channels/websocket.py::WebSocketChannel` 类的方法调用，以封装发送逻辑。
- **操作**:
    1.  **确认依赖**: 确认 `ICommunicationChannel` 和 `WebSocketChannel` 存在且包含发送方法。 (**已确认**)
    2.  **实例化 Channel**: 在 `core/connection.py` 中创建 `self.channel = WebSocketChannel(self.websocket)`。 (**已完成**)
    3.  **替换发送调用**: 查找 `core/connection.py` 及相关处理函数 (`sendAudioHandler.py`, `iotHandler.py`) 中的 `websocket.send` 调用，替换为 `channel.send_message`, `channel.send_raw_string`, `channel.send_bytes`。 (**已完成**)
    4.  **保持不变**: 接收循环 (`async for message in self.websocket:`) 和 `websocket.close()` 调用保持不变。 (**已确认**)
    5.  **无需修改 Channel**: `receive()` 或 `close()` 方法未在此步骤实现。 (**已确认**, `send_bytes` 已按需添加)
    6.  **(清理)** `websocket_wrapper.py` 不存在，无需删除。 (**已确认**)
- **理由**: 优先封装发送逻辑，风险较低。将复杂的接收循环和清理逻辑的迁移推迟到更合适的步骤（第 8 步）。
- **测试**: 测试所有需要服务器主动发送消息给客户端的场景（例如：发送欢迎消息、发送 TTS 音频数据、发送 STT 结果、发送错误信息等）。确保消息仍然能够正确发送。接收消息和连接关闭功能应保持不变。 (**需要手动测试确认**)

第 3 步：提取 Authenticator (**注意: 使用现有的 AuthMiddleware**) - **已完成确认**
- 操作：
    - 在 `core/connection.py` 的 `handle_connection`（或管理连接的类）中定位执行身份验证的代码块（例如 `await self.auth.authenticate(...)`)。
    - **(调整)** 由于 `core/auth.py` 中已存在 `AuthMiddleware` 及其 `authenticate` 方法，此步骤主要是确认 `core/connection.py` 中调用该方法的逻辑是否正确和独立，为后续将其移入 `ConnectionManager` 做准备。检查点：是否可以通过传入 `AuthMiddleware` 实例和 `headers` 来完成认证？
    - **(原始计划的移动逻辑将在第 8 步完成)**: 将 `AuthMiddleware` 的实例化和调用逻辑移入 `ConnectionManager.__init__` 和 `ConnectionManager.manage_connection`。

第 4 步：提取 StateManager
- 操作：
- 在 `core/connection.py` 中找到负责在开始时加载连接特定状态的代码（例如 `await self.memory.load_memory(...)` 或 `await self.private_config.load_or_create()`)以及在结束时保存状态的代码（例如 `await self.memory.save_memory(...)`)。
- 移动 加载逻辑到 `core/state.py` 中 `StateManager` 的 `async load(self, connection_id)` 方法。
- 移动 保存逻辑到 `StateManager` 的 `async save(self, connection_id, state_data)` 方法。
- 在 `core/connection.py` 中，导入 `StateManager`。实例化 `state_manager = StateManager()`。
- 替换 原始的加载/保存调用为 `state = await state_manager.load(...)` 和 `await state_manager.save(...)`。你需要管理状态数据的传递。
- 理由： 隔离状态持久化逻辑。
- 测试： 连接，进行交互（会修改状态），然后断开连接。重新连接并检查之前的状态是否已正确加载/持久化。

第 5 步：提取 TaskDispatcher
- 操作：
- 在 `core/connection.py` 中识别将任务放入 `TTS_Queue`、`Audio_Queue` 或提交给 `ThreadPoolExecutor` 的地方。
- 在 `core/tasks.py` 中实现 `TaskDispatcher`。它可能需要在初始化时访问队列、执行器和主事件循环（通过参数传入）。创建如下方法：
- dispatch_tts(self, text): 包含 `self.tts_queue.put_nowait(text)` 逻辑。
- dispatch_audio(self, audio_data): 包含 `self.audio_play_queue.put_nowait(audio_data)` 逻辑。
- async dispatch_plugin_task(self, func, *args): 包含 `self.loop.run_in_executor(self.executor, func, *args)` 逻辑。
- 在 `core/connection.py` 中，导入 `TaskDispatcher`。实例化 `dispatcher = TaskDispatcher(...)`（传入队列、循环、执行器）。
- 替换 所有原始的队列 put 调用和 `run_in_executor` 调用为对相应 `dispatcher` 方法的调用（例如 `dispatcher.dispatch_tts(result_text), await dispatcher.dispatch_plugin_task(...)`)。
- 理由： 集中处理启动后台任务的逻辑。
- 测试： 测试触发插件、TTS 和音频播放的场景。确保这些后台任务仍然能被正确启动。

第 6 步：填充 MessageHandler 实现 (初步复制)
- 操作：
- 在 `core/handlers/context.py` 中定义 `HandlerContext` 类/数据类，用于保存 Handler 所需的依赖项（例如 `dispatcher`、`websocket_wrapper`、`state_manager`）。
- 在 `core/connection.py` 中，找到 `_route_message`（或类似函数）内部处理文本消息的逻辑块。复制这整个逻辑块到 `core/handlers/text.py` 中 `TextMessageHandler` 的 `handle(self, message, context)` 方法内。你需要调整变量名以使用 `context` 对象（例如 `context.dispatcher.dispatch_tts(...), await context.websocket_wrapper.send_json(...)`)。
- 对处理音频消息的逻辑块执行相同操作，将其复制到 `core/handlers/audio.py` 的 `AudioMessageHandler.handle()` 中，并根据 `context` 进行调整。
- 理由： 将核心处理逻辑移动到指定的 Handler 类中，即使最初只是复制粘贴。Handler 现在包含了如何做，但尚未集成到主流程中。
- 测试： 此阶段无法进行功能测试，因为这些 Handler 尚未被调用。

第 7 步：实现 MessageRouter
- 操作：
- 在 `core/routing.py` 中实现 `MessageRouter` 类。
- 在 `core/connection.py` 的 `_route_message` 中找到判断消息类型的 `if/elif/else` 结构。
- 移动 这个决策逻辑到 `MessageRouter` 的 `route(self, message)` 方法中。
- 关键是，该方法现在不应执行处理逻辑，而应返回相应 Handler 的一个实例。
    python
    Apply to connection.p...
         # 在 MessageRouter.route 内部
         import json
         from .handlers.text import TextMessageHandler
         from .handlers.audio import AudioMessageHandler
         # 可能还需要导入 UnknownMessageHandler 或其他
         class MessageRouter:
             def route(self, message):
                 if isinstance(message, str): # 假设文本消息是字符串
                     try:
                         data = json.loads(message)
                         if data.get("type") == "text":
                             return TextMessageHandler() # 返回实例
                             # 如果需要，添加其他文本子类型的 elif
                     except json.JSONDecodeError:
                             # 如果需要处理非 JSON 文本，可能返回特定 handler
                             pass
                 elif isinstance(message, bytes): # 假设音频是字节流
                     return AudioMessageHandler() # 返回实例
                 # 根据需要添加更多路由逻辑
                 # 对于未知类型，返回默认 handler 或引发错误
                 # return UnknownMessageHandler() # 或类似
                 return None # 或者返回一个空操作的Handler
- 你可能需要稍后用上下文来实例化 Handler 或传递上下文。开始时可以简单地只返回类型。
- 理由： 隔离消息路由决策逻辑。
- 测试： 目前难以单独测试。

第 8 步：引入 ConnectionManager 并集成
- 操作： 这是最大的一步，连接所有部分。
- 在 `core/connection/manager.py` 中定义 `ConnectionManager` 类。它可能在其 `__init__` 中接收 `AuthMiddleware` (替代 Authenticator), `MessageRouter`, `TaskDispatcher`, `StateManager` 等依赖项。
- **(迁移核心逻辑)**: **移动**主要的连接处理循环 (`async for message in ...`) 以及周围的设置 (实例化 `WebSocketChannel`, 调用认证等) 和清理逻辑 (调用 `state_manager.save`, 调用 `channel.close` 或 `websocket.close`)，从 `core/connection.py` **移到** `ConnectionManager` 的 `async manage_connection(self, websocket)` 方法中。
- 修改 `manage_connection` 逻辑：
- 创建 `WebSocketChannel`: `self.channel = WebSocketChannel(websocket)`
- 认证: `if not await self.authenticator.authenticate(...)` (**注意**: 此处使用传入的 `AuthMiddleware` 实例)
- 加载状态: `state = await self.state_manager.load(...)`
- 创建 `HandlerContext`: `context = HandlerContext(dispatcher=self.dispatcher, channel=self.channel, state_manager=self.state_manager, ...)` (**注意**: 使用 `channel` 替代 `websocket_wrapper`)
- **(迁移接收循环)**: 在循环内部 (`async for message in self.channel:` 或保持 `self.websocket`): 
- 路由: `handler = self.router.route(message)`
- 处理: `if handler: await handler.handle(message, context)`
- **(迁移清理逻辑)**: 保存状态: `await self.state_manager.save(...)`
- **(迁移关闭调用)**: 确保在 `finally` 块或适当位置调用 `await self.channel.close()` (或者如果 `WebSocketChannel` 未实现 `close`，则直接调用 `await websocket.close()`)。
- 确保进行正确的异常处理。
- 修改 `app.py` (或服务器入口点)：
- 导入 `ConnectionManager` 和其他必要组件。
- 一次性实例化 `Authenticator`、`MessageRouter`、`TaskDispatcher`（传入队列/循环/执行器）、`StateManager`（如果它们是无状态的），或者根据需要为每个连接实例化。
- 在处理新 WebSocket 连接的函数（传递给 `websockets.serve` 的那个）中，不再调用旧的 `handle_connection`，而是创建一个 `ConnectionManager` 实例并调用其 `manage_connection` 方法：
    python
    Apply to connection.p...
             # 在服务器处理新连接的函数内部
             authenticator = Authenticator() # 或获取单例
             router = MessageRouter()
             # ... 实例化 dispatcher, state_manager ...
             manager = ConnectionManager(authenticator, router, dispatcher, state_manager)
             await manager.manage_connection(websocket)
- 理由： 用新的、协调式的结构替换掉单一庞大的连接处理逻辑。原来的 `core/connection.py` 会变得非常小，甚至可能被废弃。
- 测试： 这是关键的集成测试。 测试所有功能：连接、认证、发送文本/音频、触发插件、TTS、音频播放、状态持久化、断开连接。

第 9 步：精炼 Handler 内部逻辑 (结构调整后)
- 操作 (可选，可稍后进行)： 既然结构已经稳固，现在可以审查 `TextMessageHandler` 和 `AudioMessageHandler` 中的 `handle` 方法了。它们目前包含的是原始复制的逻辑。现在可以在这些方法内部进行重构以提高清晰度，将它们分解成更小的私有方法，改进错误处理等，而无需改变整体架构。
- 理由： 在逻辑被放置到正确位置后，提高 Handler 逻辑的质量。
- 测试： 重新测试受 Handler 重构影响的特定功能。

第 10 步：清理
- 操作： 从 `core/connection.py` 中删除旧的、现在未使用的函数和逻辑。如果该文件现在为空或几乎为空，考虑删除它。移除整个项目中未使用的导入。
- 理由： 移除无用代码。
- 测试： 最后检查一切是否仍然正常工作。