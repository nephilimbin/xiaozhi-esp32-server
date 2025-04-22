第 0 步：准备工作
- 备份： 为你当前可工作的代码创建备份或提交（commit）。
- 测试： 确保你可以轻松启动服务器并测试基本的连接、消息发送/接收，理想情况下还包括 TTS/音频播放功能。

第 1 步：创建新文件和空类 (**已完成**)
1.  `core/connection/manager.py` (包含 `class ConnectionManager:`) - **已创建**
2.  `core/connection/state.py` (包含 `class StateManager:`) - **已创建**
3.  `core/connection/tasks.py` (包含 `class TaskDispatcher:`) - **已创建**
4.  `core/auth.py` (已存在 `AuthMiddleware`，将使用它代替创建`Authenticator`) - **已存在**
5.  `core/routing.py` (包含 `class MessageRouter:`) - **已创建**
6.  `core/message_handlers/base.py` (包含 `BaseMessageHandler` 抽象类) - **已创建**
7.  `core/message_handlers/text.py` (包含 `TextMessageHandler`) - **已创建**
8.  `core/message_handlers/audio.py` (包含 `AudioMessageHandler`) - **已创建**
9.  `core/channels/websocket_wrapper.py` (包含 `class WebSocketWrapper:`) - **已确认存在** (但请看下面第 2 步的讨论)
10. `core/message_handlers/context.py` (包含 `HandlerContext`) - **已创建**
- 理由： 建立目标文件结构，同时不破坏任何现有功能。
- 测试： 启动服务器。它应该和之前完全一样运行，因为没有逻辑被改变。

第 2 步：使用 WebSocketChannel 替换发送调用 (调整后方案) - **已完成**
- **目标**: 将 `core/connection.py` 中对底层 `websocket.send()` 的直接调用，替换为通过你现有的 `core/channels/websocket.py::WebSocketChannel` 类的方法调用，以封装发送逻辑。
- **操作**:
    1.  **确认依赖**: 确认 `ICommunicationChannel` 和 `WebSocketChannel` 存在且包含发送方法。 (**已确认**)
    2.  **实例化 Channel**: 在 `core/connection.py` 中创建 `self.channel = WebSocketChannel(self.websocket)`。 (**已完成**)
    3.  **替换发送调用**: 查找 `core/connection.py` 及相关处理函数 (`sendAudioHandler.py`, `iotHandler.py`) 中的 `websocket.send` 调用，替换为 `channel.send_message`, `channel.send_raw_string`, `channel.send_bytes`。 (**已完成**)
    4.  **保持不变**: 接收循环 (`async for message in self.websocket:`) 和 `websocket.close()` 调用保持不变。 (**已确认**)
    5.  **无需修改 Channel**: `receive()` 或 `close()` 方法未在此步骤实现。 (**已确认**, `send_bytes` 已按需添加)
    6.  **(清理)** `websocket_wrapper.py` 不存在，无需删除。 (**已确认**)
- **理由**: 优先封装发送逻辑，风险较低。将复杂的接收循环和清理逻辑的迁移推迟到更合适的步骤（第 9' 步）。
- **测试**: 测试所有需要服务器主动发送消息给客户端的场景（例如：发送欢迎消息、发送 TTS 音频数据、发送 STT 结果、发送错误信息等）。确保消息仍然能够正确发送。接收消息和连接关闭功能应保持不变。 (**需要手动测试确认**)

第 3 步：提取 Authenticator (**注意: 使用现有的 AuthMiddleware**) - **已完成确认**
- 操作：
    - 在 `core/connection.py` 的 `handle_connection`（或管理连接的类）中定位执行身份验证的代码块（例如 `await self.auth.authenticate(...)`)。
    - **(调整)** 由于 `core/auth.py` 中已存在 `AuthMiddleware` 及其 `authenticate` 方法，此步骤主要是确认 `core/connection.py` 中调用该方法的逻辑是否正确和独立，为后续将其移入 `ConnectionManager` 做准备。检查点：是否可以通过传入 `AuthMiddleware` 实例和 `headers` 来完成认证？
    - **(移动逻辑将在第 9' 步完成)**: 将 `AuthMiddleware` 的实例化和调用逻辑移入 `ConnectionManager.__init__` 和 `ConnectionManager.manage_connection`。

第 4 步：提取 StateManager - **已完成**
- 操作：
- 在 `core/connection.py` 中找到负责在开始时加载连接特定状态的代码（例如 `await self.memory.load_memory(...)` 或 `await self.private_config.load_or_create()`)以及在结束时保存状态的代码（例如 `await self.memory.save_memory(...)`)。
- 移动 加载逻辑到 `core/state.py` 中 `StateManager` 的 `async load(self, connection_id)` 方法。
- 移动 保存逻辑到 `StateManager` 的 `async save(self, connection_id, state_data)` 方法。
- 在 `core/connection.py` 中，导入 `StateManager`。实例化 `state_manager = StateManager()`。
- 替换 原始的加载/保存调用为 `state = await state_manager.load(...)` 和 `await state_manager.save(...)`。你需要管理状态数据的传递。
- 理由： 隔离状态持久化逻辑。
- 测试： 连接，进行交互（会修改状态），然后断开连接。重新连接并检查之前的状态是否已正确加载/持久化。

第 5 步：提取 TaskDispatcher - **已完成**
- 操作：
- 在 `core/connection.py` (实际为 `core/connection_handler.py`) 中识别将任务放入 `TTS_Queue`、`Audio_Queue` 或提交给 `ThreadPoolExecutor` 的地方。
- 在 `core/tasks.py` (实际为 `core/connection/tasks.py`) 中实现 `TaskDispatcher`。它可能需要在初始化时访问队列、执行器和主事件循环（通过参数传入）。创建如下方法：
- dispatch_tts(self, text): 包含 `self.tts_queue.put_nowait(text)` 逻辑。
- dispatch_audio(self, audio_data): 包含 `self.audio_play_queue.put_nowait(audio_data)` 逻辑。
- async dispatch_plugin_task(self, func, *args): 包含 `self.loop.run_in_executor(self.executor, func, *args)` 逻辑。
- 在 `core/connection.py` 中，导入 `TaskDispatcher`。实例化 `dispatcher = TaskDispatcher(...)`（传入队列、循环、执行器）。
- 替换 所有原始的队列 put 调用和 `run_in_executor` 调用为对相应 `dispatcher` 方法的调用（例如 `dispatcher.dispatch_tts(result_text), await dispatcher.dispatch_plugin_task(...)`)。
- 理由： 集中处理启动后台任务的逻辑。
- 测试： 测试触发插件、TTS 和音频播放的场景。确保这些后台任务仍然能被正确启动。

--- 新的重构计划 (替代原 6-10) ---

第 6 步：创建 `HandlerContext` 并初步填充 `MessageHandler` - 
- 操作：
  - 在 `core/message_handlers/context.py` 中定义 `HandlerContext` 类，包含所有必要的依赖项。
  - 将 `core/handle/textHandler.py` 中的逻辑复制到 `core/message_handlers/text.py` 的 `TextMessageHandler.handle`，并初步适配 `context`。
  - 将 `core/handle/receiveAudioHandler.py` 中的逻辑复制到 `core/message_handlers/audio.py` 的 `AudioMessageHandler.handle`，并初步适配 `context`。
- 理由： 将处理逻辑移动到目标类，为后续集成做准备。
- 测试： 此阶段无法直接测试 Handler 功能。

第 7' 步：在 `ConnectionHandler` 中集成 `MessageRouter` (仅路由，可测试) - **已完成**
- **目标**: 在不改变现有处理流程的情况下，验证 `MessageRouter` 的路由逻辑是否正确。
- **操作**:
  - **(前置)**: 确保 `core/routing.py` 中 `MessageRouter` 类存在并包含 `route` 方法占位符。(**代码待恢复到占位符**)
  - **7a' (修改 `ConnectionHandler.__init__`)**:
    - 导入 `MessageRouter`。
    - 在 `ConnectionHandler.__init__` 中创建 `self.router = MessageRouter()`。
  - **7b' (修改 `ConnectionHandler._route_message`)**:
    - 在方法开始处，调用 `handler_instance = self.router.route(message)`。
    - **保留** 对 `await handleTextMessage(...)` 和 `await handleAudioMessage(...)` 的原始调用。
    - 添加日志记录，如 `self.logger.bind(tag=TAG).debug(f"Router selected handler: {type(handler_instance)}")`。
- **理由**: 验证路由逻辑，同时保持现有功能稳定。
- **测试 (关键!)**:
  - 启动服务器。
  - 发送文本和音频消息。
  - **验证**: 日志中是否打印了正确的 Handler 类型？核心功能是否仍然正常工作（通过旧路径）？

第 8' 步：逐步将处理逻辑切换到新的 Handlers (在 `ConnectionHandler` 内部，可测试) - **已完成**
- **目标**: 逐个将消息处理逻辑从旧函数切换到新的 Handler 类，并验证其正确性。
- **操作**:
  - **(前置)**: 确保 `TextMessageHandler` 和 `AudioMessageHandler` 中包含从第 6 步复制并适配的逻辑。
  - **8a' (切换文本处理)**:
    - **修改 `ConnectionHandler._route_message`**:
      - 调用 `handler_instance = self.router.route(message)`。
      - `if isinstance(handler_instance, TextMessageHandler):`
        - 添加创建 `HandlerContext` 的逻辑 (`context = self._create_handler_context()`)。 (需要实现 `_create_handler_context` 辅助方法)
        - **调用**: `await handler_instance.handle(message, context)`。
        - **移除**: 对 `handleTextMessage` 的调用。
      - `elif isinstance(handler_instance, AudioMessageHandler):`
        - **保留**: 对 `handleAudioMessage` 的调用。
    - **(适配)**: 检查并调整 `TextMessageHandler` 及其依赖的辅助函数以正确使用 `context`。
  - **测试 (文本)**:
    - 启动服务器。
    - **重点测试文本消息场景**。
    - **验证**: 文本功能是否通过新 Handler 正常工作？音频功能是否通过旧路径正常工作？
  - **8b' (切换音频处理)**:
    - **修改 `ConnectionHandler._route_message`**:
      - `if isinstance(handler_instance, TextMessageHandler):`
        - 保持调用 `handler_instance.handle`。
      - `elif isinstance(handler_instance, AudioMessageHandler):`
        - 创建 `HandlerContext`: `context = self._create_handler_context()`。
        - **调用**: `await handler_instance.handle(message, context)`。
        - **移除**: 对 `handleAudioMessage` 的调用。
    - **(适配)**: 检查并调整 `AudioMessageHandler` 及其依赖的辅助函数以正确使用 `context`。
  - **测试 (音频)**:
    - 启动服务器。
    - **重点测试音频消息场景**。
    - **验证**: 音频功能是否通过新 Handler 正常工作？文本功能是否仍然通过新 Handler 正常工作？
- **理由**: 隔离 Handler 的集成测试，降低风险。
- **注意**:
  - 当前 `TextMessageHandler` 中处理 `listen` -> `stop` 时，为了立即触发 `AudioMessageHandler` 处理缓存音频，临时调用了 `context.conn_handler._route_message(b"")`。这部分逻辑将在 Step 9' 引入 `ConnectionManager` 管理主消息循环后自然消失。
  - 当前 `TextMessageHandler` 和 `AudioMessageHandler` 内部直接修改了 `context` 中的状态属性（如 `client_voice_stop`），并且 `TextMessageHandler` 还尝试更新了 `conn_handler` 上的状态。这是一种临时解决方案，将在 Step 9' 中由 `ConnectionManager` 统一管理状态后进行优化。
  - 部分辅助函数（如 `send_stt_message`, `startToChat`, `handleIotDescriptors` 等）目前是通过将 `context` 作为第一个参数传递给它们来工作的，这需要在 Step 10' 清理阶段进行重构，使其完全依赖 `context` 或通过 `context` 访问所需的服务/调度器。

第 9' 步：引入 `ConnectionManager` 并迁移整体逻辑 (可测试)
- **目标**: 将 `ConnectionHandler` 的职责转移到新的 `ConnectionManager`，完成结构调整。
- **操作**:
  - **9a' (准备 `ConnectionManager`)**:
    - 确保 `core/connection/manager.py` 中的 `ConnectionManager.__init__` 接受所有必要依赖 (Config, Logger, AuthMiddleware, Router, Dispatcher, StateManager, Executor, AI 模块, AuthCodeGenerator 等)。
  - **9b' (实现 `ConnectionManager.manage_connection`)**:
    - **整体移动**: 将 `ConnectionHandler.handle_connection` 的 `try...except...finally` 块（包括认证、加载状态、创建Channel、*已修改为使用Router和Handlers的消息循环*、保存状态、关闭等）移动到 `ConnectionManager.manage_connection`。
    - **适配**: 确保移动的代码使用 `ConnectionManager` (`self`) 的依赖项。
    - **迁移辅助逻辑**: 确保创建 `HandlerContext` 的逻辑 (`_create_handler_context`) 也一并迁移或在 `manage_connection` 内实现。
  - **9c' (修改服务器入口点 `WebSocketServer._handle_connection`)**:
    - 导入 `ConnectionManager`。
    - **创建**: `ConnectionManager` 实例，传递所有依赖 (可能需要在 `WebSocketServer` 中先实例化 Router, Dispatcher, StateManager)。
    - **不再创建**: `ConnectionHandler` 实例。
    - **调用**: `await manager.manage_connection(websocket)`。
- **理由**: 将连接管理逻辑集中到 `ConnectionManager`，完成核心重构。
- **测试 (关键!)**:
  - 启动服务器。
  - **执行全面的回归测试** (连接、认证、文本、音频、插件、状态、断开)。
  - **验证**: 整体功能是否正常？

第 10' 步：精炼与清理
- **目标**: 移除旧代码，优化新代码结构。
- **操作**:
  - 精炼 `TextMessageHandler` 和 `AudioMessageHandler` 内部逻辑。
  - 适配所有辅助函数，确保只依赖 `context`。
  - 移除旧的 `core/handle/` 下的文件 (`textHandler.py`, `receiveAudioHandler.py` 等)。
  - 移除旧的 `ConnectionHandler` 类 (如果它变空了)。
  - 清理未使用的导入和代码。
- **理由**: 提高代码质量和可维护性。
- **测试**: 在每次重要精炼或清理后进行测试。