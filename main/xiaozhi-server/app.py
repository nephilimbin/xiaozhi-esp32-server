import asyncio
import sys
import signal
from config.settings import load_config, check_config_file
from core.websocket_server import WebSocketServer
from core.utils.util import check_ffmpeg_installed
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

async def wait_for_exit():
    """Windows 和 Linux 兼容的退出监听"""
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform == "win32":
        # Windows: 用 sys.stdin.read() 监听 Ctrl + C
        await loop.run_in_executor(None, sys.stdin.read)
    else:
        # Linux/macOS: 用 signal 监听 Ctrl + C
        def stop():
            stop_event.set()
        loop.add_signal_handler(signal.SIGINT, stop)
        loop.add_signal_handler(signal.SIGTERM, stop)  # 支持 kill 进程
        await stop_event.wait()

async def main():
    check_config_file()
    check_ffmpeg_installed()
    config = load_config()

    # 启动 WebSocket 服务器
    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())
    server_closed = False

    try:
        await wait_for_exit()  # 监听退出信号
    except asyncio.CancelledError:
        logger.bind(tag=TAG).info("主任务被取消...")
    finally:
        logger.bind(tag=TAG).info("开始关闭服务器...")
        if not server_closed and hasattr(ws_server, 'close') and callable(ws_server.close):
            try:
                logger.bind(tag=TAG).info("调用 ws_server.close()...")
                await ws_server.close()
                server_closed = True
                logger.bind(tag=TAG).info("ws_server.close() 完成.")
            except Exception as e:
                logger.bind(tag=TAG).error(f"关闭 ws_server 时出错: {e}", exc_info=True)

        # 即使服务器关闭出错，仍然尝试取消和等待任务
        if not ws_task.done():
            logger.bind(tag=TAG).info("取消 ws_task...")
            ws_task.cancel()
            try:
                await ws_task
                logger.bind(tag=TAG).info("ws_task 等待完成.")
            except asyncio.CancelledError:
                logger.bind(tag=TAG).info("ws_task 被成功取消.")
            except Exception as e:
                logger.bind(tag=TAG).error(f"等待 ws_task 时出错: {e}", exc_info=True)
        else:
            logger.bind(tag=TAG).info("ws_task 已经完成.")

        logger.bind(tag=TAG).info("服务器已关闭，程序退出。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.bind(tag=TAG).info("手动中断，程序终止。")
