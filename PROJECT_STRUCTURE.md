main/xiaozhi-server/
├── app.py                 # Web 应用入口
├── config.yaml            # 主要配置文件
├── mcp_server_settings.json # 特定配置文件 (MCP 相关)
├── monitor.py             # 监控脚本
├── performance_tester.py  # 性能测试脚本
├── requirements.txt       # Python 依赖文件 (pip)
├── pyproject.toml         # Python 项目配置文件 (Poetry)
├── poetry.lock            # Poetry 锁定的依赖版本
├── poetry.toml            # Poetry 配置文件
├── docker-compose.yml     # Docker Compose 配置文件
├── core/                  # 核心业务逻辑模块
│   ├── connection_handler.py # 负责连接ws与客户登陆验证、创建信息连接及主要任务调度的入口
│   ├── connection/           # 协助connection_handler构建一些通用函数
│   ├── websocket_server.py   # 创建ws服务及连接的入口的
│   ├── message_handlers/     # 处理服务的信息主要模块
│   ├── plan.md               # 【临时】记录代码优化的过程与计划，后期删除
│   ├── handle/               # 通用处理信息的工具
│   ├── mcp/                  # MCP服务模块
│   ├── utils/                # 一般通用工具
│   ├── providers/            # 处理信息的主类文件的供给模块
│   ├── channels/             # 处理各种协议的主模块的
│   └── auth.py               # 验证用户授权的文件
├── config/                   # 配置相关模块
│   ├── logger.py             # 日志记录的规则
│   ├── assets/               # 初始化的一些资源文件
│   ├── config_loader.py      # 统一日志管理文件入口
│   ├── manage_api_client.py  # API POST请求接口文件（暂时用不到）
│   ├── settings.py           # 系统配置管理文件
│   └── private_config.py     # 私有化用户配置管理文件
├── data/                  # 数据存储目录 (可能包含运行时配置或数据)
│   ├── .mcp_server_settings.json
│   └── .private_config.yaml
├── models/                # 数据/AI 模型
│   ├── SenseVoiceSmall/
│   └── snakers4_silero-vad/
├── plugins_func/          # 特定功能模块 (待讨论命名)
│   ├── register.py
│   ├── loadplugins.py
│   └── functions/
├── music/                 # 音乐文件存储
│   ├── 廉波老矣，尚能饭否.mp3
│   ├── 中秋月.mp3
│   └── 一念千年_国风版.mp3
├── test/                  # 测试相关文件
│   ├── test_page.html
│   ├── opus_test/
│   ├── libopus.js
│   └── abbreviated_version/
├── tmp/                   # 临时文件/日志目录
│   └── server.log
└── mermaid/               # Mermaid 图表文件
    ├── classgraph.mmd
    └── threads.mmd