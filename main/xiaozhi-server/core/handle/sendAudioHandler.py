from config.logger import setup_logging
import json
import asyncio
import time
from core.utils.util import (
    remove_punctuation_and_length,
    get_string_no_punctuation_or_emoji,
)

TAG = __name__
logger = setup_logging()


async def sendAudioMessage(conn, audios, text, text_index=0):
    # 发送句子开始消息
    if text_index == conn.tts_first_text_index:
        logger.bind(tag=TAG).info(f"发送第一段语音: {text}")
    await send_tts_message(conn, "sentence_start", text)

    # 播放音频
    await sendAudio(conn, audios)

    await send_tts_message(conn, "sentence_end", text)

    # 发送结束消息（如果是最后一个文本）
    if conn.llm_finish_task and text_index == conn.tts_last_text_index:
        await send_tts_message(conn, "stop", None)
        if conn.close_after_chat:
            await conn.close()


# 播放音频
async def sendAudio(conn, audios):
    # 流控参数优化
    frame_duration = 60  # 帧时长（毫秒），匹配 Opus 编码
    start_time = time.perf_counter()
    play_position = 0

    # 预缓冲：发送前 3 帧
    pre_buffer = min(3, len(audios))
    for i in range(pre_buffer):
        await conn.channel.send_bytes(audios[i])

    # 正常播放剩余帧
    for opus_packet in audios[pre_buffer:]:
        if conn.client_abort:
            logger.bind(tag=TAG).info("Client aborted during audio send.")
            return

        # 计算预期发送时间
        expected_time = start_time + (play_position / 1000)
        current_time = time.perf_counter()
        delay = expected_time - current_time
        if delay > 0:
            await asyncio.sleep(delay)

        await conn.channel.send_bytes(opus_packet)

        play_position += frame_duration


async def send_tts_message(conn, state, text=None):
    """发送 TTS 状态消息"""
    message = {"type": "tts", "state": state, "session_id": conn.session_id}
    if text is not None:
        message["text"] = text

    # TTS播放结束
    if state == "stop":
        tts_notify = conn.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = conn.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            audios, duration = conn.tts.audio_to_opus_data(stop_tts_notify_voice)
            await sendAudio(conn, audios)
        conn.clearSpeakStatus()

    # Use channel to send the message
    await conn.channel.send_message(message)


async def send_stt_message(conn, text):
    """发送 STT 状态消息"""
    stt_text = get_string_no_punctuation_or_emoji(text)
    stt_message = {"type": "stt", "text": stt_text, "session_id": conn.session_id}
    await conn.channel.send_message(stt_message)

    llm_thinking_message = {
        "type": "llm",
        "text": "😊",
        "emotion": "happy",
        "session_id": conn.session_id,
    }
    await conn.channel.send_message(llm_thinking_message)

    await send_tts_message(conn, "start")
