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
    if not conn.channel:
        logger.bind(tag=TAG).error("Communication channel not available.")
        return

    session_id = conn.session_id
    # Check if audios is a list or None
    num_packets = len(audios) if isinstance(audios, list) else 0
    logger.bind(tag=TAG).info(f"[sendAudioMessage] Starting for index {text_index}, packets: {num_packets}, text: '{text}'")

    start_msg = {
        "type": "tts",
        "state": "start",
        "session_id": session_id,
        "index": text_index,
    }

    # 第一个语音开始，同时传递文本
    if conn.tts_first_text_index == text_index:
        start_msg["text"] = text
        logger.bind(tag=TAG).info(f"[sendAudioMessage] Sending first sentence start for index {text_index}: {start_msg}")
    else:
        start_msg["text"] = ""
        logger.bind(tag=TAG).info(f"[sendAudioMessage] Sending sentence start for index {text_index}: {start_msg}")

    sentence_start_msg = {
        "type": "tts",
        "state": "sentence_start",
        "text": text,
        "session_id": session_id,
        "index": text_index,
    }
    sentence_end_msg = {
        "type": "tts",
        "state": "sentence_end",
        "text": text,
        "session_id": session_id,
        "index": text_index,
    }
    end_msg = {
        "type": "tts",
        "state": "end",
        "session_id": session_id,
        "index": text_index,
    }

    try:
        # 发送开始信号
        # await conn.channel.send_message(start_msg)
        # 发送句子开始信号
        logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending sentence_start for index {text_index}")
        await conn.channel.send_message(sentence_start_msg)

        # 流式发送Opus数据包
        if isinstance(audios, list) and audios:
            packet_index = 0
            for packet in audios:
                if conn.client_abort:
                    logger.bind(tag=TAG).warning(f"[sendAudioMessage] Client aborted during Opus stream for index {text_index}.")
                    break
                if packet:
                    logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending packet {packet_index + 1}/{num_packets} for index {text_index}, size: {len(packet)}")
                    await conn.channel.send_bytes(packet)
                    # logger.bind(tag=TAG).debug(f"发送语音包完成: {len(packet)}字节")
                    await asyncio.sleep(0.015)  # 短暂休眠，避免发送过快，给网络和客户端处理时间
                    packet_index += 1
                else:
                    logger.bind(tag=TAG).warning(f"[sendAudioMessage] Skipping empty packet {packet_index + 1}/{num_packets} for index {text_index}")
                    packet_index += 1
            logger.bind(tag=TAG).info(f"[sendAudioMessage] Finished sending {packet_index} packets for index {text_index}")
        else:
            logger.bind(tag=TAG).warning(f"[sendAudioMessage] No Opus packets to send for index {text_index}")


        # 发送句子结束信号
        logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending sentence_end for index {text_index}")
        await conn.channel.send_message(sentence_end_msg)

        # 检查是否是最后一个文本片段
        if conn.llm_finish_task and conn.tts_last_text_index == text_index:
            logger.bind(tag=TAG).info(f"[sendAudioMessage] Sending final end signal as index {text_index} is the last.")
            # Optionally send an empty packet as an explicit stream end signal for the client
            # empty_packet = bytes()
            # logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending empty end packet for index {text_index}") # Added log
            # await conn.channel.send_bytes(empty_packet)
            # await asyncio.sleep(0.02) # Ensure empty packet is sent before final JSON

            # 发送最后的结束信号
            await conn.channel.send_message(end_msg)
            conn.clearSpeakStatus() # 清理状态
            # 如果设置了 chat_and_close，则关闭连接
            if conn.close_after_chat:
                logger.bind(tag=TAG).info("[sendAudioMessage] Closing connection after chat.")
                await conn.close()


    except Exception as e:
        logger.bind(tag=TAG).error(f"[sendAudioMessage] Error sending audio for index {text_index}: {e}", exc_info=True)
        # Optionally try to send an error message to client
        try:
            error_msg = {
                "type": "error",
                "message": f"Error sending audio for index {text_index}",
                "session_id": session_id,
                "index": text_index,
            }
            await conn.channel.send_message(error_msg)
        except Exception as send_err:
            logger.bind(tag=TAG).error(f"[sendAudioMessage] Failed to send error message to client: {send_err}")
        # Maybe clear status on error too?
        conn.clearSpeakStatus()

    logger.bind(tag=TAG).info(f"[sendAudioMessage] Finished processing index {text_index}")


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

    time.sleep(0.1)
