from config.logger import setup_logging
import json
from core.handle.abortHandler import handleAbortMessage
from core.handle.helloHandler import handleHelloMessage
from core.utils.util import remove_punctuation_and_length
from core.handle.receiveAudioHandler import startToChat, handleAudioMessage
from core.handle.sendAudioHandler import send_stt_message, send_tts_message
from core.handle.iotHandler import handleIotDescriptors, handleIotStatus
import asyncio
# Import the interface from the new location
from ..channels.interface import ICommunicationChannel

TAG = __name__
logger = setup_logging()


async def handleTextMessage(conn, message, channel: ICommunicationChannel):
    """处理文本消息"""
    logger.bind(tag=TAG).info(f"收到文本消息：{message}")
    try:
        msg_json = json.loads(message)
        if isinstance(msg_json, int):
            logger.bind(tag=TAG).debug(f"Received integer, sending raw string: {message}")
            await channel.send_raw_string(message)
            return
        if msg_json["type"] == "hello":
            await handleHelloMessage(conn, channel)
        elif msg_json["type"] == "abort":
            await handleAbortMessage(conn, channel)
        elif msg_json["type"] == "listen":
            if "mode" in msg_json:
                conn.client_listen_mode = msg_json["mode"]
                logger.bind(tag=TAG).debug(f"客户端拾音模式：{conn.client_listen_mode}")
            if msg_json["state"] == "start":
                conn.client_have_voice = True
                conn.client_voice_stop = False
            elif msg_json["state"] == "stop":
                conn.client_have_voice = True
                conn.client_voice_stop = True
                if len(conn.asr_audio) > 0:
                    await handleAudioMessage(conn, b"")
            elif msg_json["state"] == "detect":
                conn.asr_server_receive = False
                conn.client_have_voice = False
                conn.asr_audio.clear()
                if "text" in msg_json:
                    text = msg_json["text"]
                    _, text = remove_punctuation_and_length(text)

                    # 识别是否是唤醒词
                    is_wakeup_words = text in conn.config.get("wakeup_words")
                    # 是否开启唤醒词回复
                    enable_greeting = conn.config.get("enable_greeting", True)

                    if is_wakeup_words and not enable_greeting:
                        # 如果是唤醒词，且关闭了唤醒词回复，就不用回答
                        await send_stt_message(conn, text)
                        await send_tts_message(conn, "stop", None)
                    else:
                        # 否则需要LLM对文字内容进行答复
                        await startToChat(conn, text)
        elif msg_json["type"] == "iot":
            if "descriptors" in msg_json:
                asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
            if "states" in msg_json:
                asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
    except json.JSONDecodeError:
        logger.bind(tag=TAG).warning(f"Received non-JSON message, sending raw string: {message}")
        await channel.send_raw_string(message)
