---
description: 
globs: 
alwaysApply: false
---
# 重构计划与进度

为了解决 `handle` 目录中类对 `connection` 对象的紧密耦合问题，提高代码的可测试性、可维护性和灵活性，进行以下结构调整：

**第一步：定义通信抽象接口 (已完成)**

*   **目标:** 解耦处理器与具体的连接实现。
*   **行动:** 创建一个抽象基类 `ICommunicationChannel`，定义核心通信方法。
*   **状态:** 已完成。`ICommunicationChannel` 定义在 `core/channels/interface.py` 中。

**第二步：重构处理器类 (进行中)**

*   **目标:** 使处理器依赖于抽象接口而非具体实现。
*   **行动:** 逐个修改 `handle` 目录下的处理器类/函数。
*   **状态:**
    *   `handleAbortMessage` (`core/handle/abortHandler.py`): 已重构。
    *   `handleHelloMessage` (`core/handle/helloHandler.py`): 已重构。
    *   `handleTextMessage` (`core/handle/textHandler.py`): 签名已修改，内部通信调用已重构。
    *   导入路径已更新以适应 `channels` 目录结构。
    *   **下一步:** 重构 `sendAudioHandler.py` 中的函数。

**第三步：实现具体的通信类 (已完成)**

*   **目标:** 封装具体的连接技术。
*   **行动:** 创建实现 `ICommunicationChannel` 的具体类。
*   **状态:** 已完成 `WebSocketChannel`，位于 `core/channels/websocket.py`。旧的 `core/communication.py` 已删除。

**第四步：引入依赖注入 (已完成)**

*   **目标:** 管理对象的创建和依赖关系。
*   **行动:** 在 `ConnectionHandler` 中创建并传递 `WebSocketChannel` 实例。
*   **状态:** 已完成。`ConnectionHandler` (`core/connection.py`) 现在导入并创建 `WebSocketChannel` (从 `core/channels/websocket.py`)，并通过 `_route_message` 传递给 `handleTextMessage`。导入路径已更新。

**第五步：配置管理 (待办)**

*   **目标:** 将连接相关的配置与代码逻辑分离。
*   **行动:** 待定。

**第六步：异步处理 (已符合)**

*   **目标:** 确保架构能有效处理 I/O 密集型操作。
*   **行动:** 接口和实现已使用 `async def`。

---

## 原始计划描述

为了解决上述缺点，提高代码的可测试性、可维护性和灵活性，可以进行以下结构调整：
第一步：定义通信抽象接口
目标: 解耦处理器与具体的连接实现。
行动: 创建一个抽象基类（ABC）或接口（例如 ICommunicationChannel），定义处理器与外部通信所需的核心方法（如 send_message(data), broadcast(data) 等）。这个接口不应包含任何具体连接技术的细节。
第二步：重构处理器类
目标: 使处理器依赖于抽象接口而非具体实现。
行动: 修改 handle 目录下的所有处理器类，让它们依赖于 ICommunicationChannel 接口，而不是具体的 connection 对象。在处理器内部，调用接口定义的方法进行通信。
第三步：实现具体的通信类
目标: 封装具体的连接技术。
行动: 创建一个或多个实现了 ICommunicationChannel 接口的具体类。例如，可以创建一个 WebSocketChannel 类，它在其内部持有并管理实际的 connection 对象，并实现 send_message 等方法来通过 WebSocket 发送数据。
第四步：引入依赖注入 (Dependency Injection - DI)
目标: 管理对象的创建和依赖关系，将通信实现注入到处理器中。
行动:
在应用程序的启动入口（如 main.py），根据当前的配置或连接类型，创建具体的通信类实例（如 WebSocketChannel）。
在创建处理器实例时，将这个通信类的实例（作为 ICommunicationChannel 类型）注入到处理器的构造函数或设置方法中。
可以考虑使用依赖注入容器库（如 python-dependency-injector）来简化和自动化这个过程，尤其是在依赖关系变得复杂时。
第五步：配置管理
目标: 将连接相关的配置（如 IP 地址、端口、认证信息等）与代码逻辑分离。
行动: 将这些配置信息移到配置文件（如 .env, config.yaml）中，并在应用程序启动时读取配置来初始化通信类。
第六步：异步处理 (如果适用)
目标: 确保架构能有效处理 I/O 密集型操作。
行动: 如果项目使用了异步 I/O（如 asyncio），确保 ICommunicationChannel 接口及其实现都是异步兼容的（使用 async def）。处理器类也应相应地使用 await 来调用通信方法。
优化的好处:
松耦合: 处理器不再关心具体的通信方式，只关心通信接口定义的功能。
高可测试性: 可以轻松地为 ICommunicationChannel 创建模拟（Mock）对象，用于单元测试处理器逻辑，无需真实的连接。
高灵活性和可扩展性: 更容易替换或添加新的通信方式（例如，增加一个 HTTP 回调通道），只需实现新的 ICommunicationChannel 子类，而无需修改现有处理器。
职责更清晰: 处理器专注于业务逻辑，通信类专注于通信细节。
这个计划提供了一个从当前结构向更松耦合、更健壮的设计演进的路径。每一步都可以在不破坏现有功能的前提下逐步实施。

重要原则：
1、仅仅先对原项目代码的结构进行优化，让connection.py的代码类更加合理、科学、符合solid原则。不要随意修改原有项目中的代码类或者函数声明、命名、调用逻辑等。如果需要优化代码逻辑，我会单独告诉你。
2、如果新建文件或者新建类，请一个个建立。建立后我会先测试下调整的内容。以免出现无法解决的问题。