from config.logger import setup_logging
import asyncio
import time
from core.utils.util import (
    get_string_no_punctuation_or_emoji,
)
from core.message_handlers.messages import MessageFactory
import typing
if typing.TYPE_CHECKING:
    from core.message_handlers.context import HandlerContext

TAG = __name__
logger = setup_logging()


async def sendAudioMessage(context: 'HandlerContext', audios, text, text_index=0):
    if not context.channel:
        logger.bind(tag=TAG).error("Communication channel not available.")
        return

    session_id = context.session_id
    # Check if audios is a list or None
    # num_packets = len(audios) if isinstance(audios, list) else 0
    # logger.bind(tag=TAG).info(f"[sendAudioMessage] Starting for index {text_index}, packets: {num_packets}, text: '{text}'")

    # Create messages using MessageFactory
    # start_text = None
    # if context.tts_first_text_index == text_index:
    #     start_text = text
    #     logger.bind(tag=TAG).info(f"[sendAudioMessage] Preparing first sentence start for index {text_index} with text.")
    # start_msg = MessageFactory.create_tts_start_message(session_id, text_index, start_text)
    # end_msg = MessageFactory.create_tts_end_message(session_id, text_index)
    sentence_start_msg = MessageFactory.create_tts_state_message(session_id, MessageFactory.TTS_STATE_SENTENCE_START, text)
    sentence_end_msg = MessageFactory.create_tts_state_message(session_id, MessageFactory.TTS_STATE_SENTENCE_END, text)
    sentence_stop_msg = MessageFactory.create_tts_state_message(session_id, MessageFactory.TTS_STATE_STOP, None)

    try:
        # 发送开始信号
        # await context.channel.send_message(start_msg)
        # 发送句子开始信号
        logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending sentence_start for index {text_index}")
        await context.channel.send_message(sentence_start_msg)

        # 流式发送Opus数据包
        # if isinstance(audios, list) and audios:
        #     packet_index = 0
        #     for packet in audios:
        #         if context.client_abort:
        #             logger.bind(tag=TAG).warning(f"[sendAudioMessage] Client aborted during Opus stream for index {text_index}.")
        #             break
        #         if packet:
        #             # logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending packet {packet_index + 1}/{num_packets} for index {text_index}, size: {len(packet)}")
        #             await context.channel.send_bytes(packet)
        #             # logger.bind(tag=TAG).debug(f"发送语音包完成: {len(packet)}字节")
        #             await asyncio.sleep(0.01)  # 短暂休眠，避免发送过快，给网络和客户端处理时间
        #             packet_index += 1
        #         else:
        #             logger.bind(tag=TAG).warning(f"[sendAudioMessage] Skipping empty packet {packet_index + 1}/{num_packets} for index {text_index}")
        #             packet_index += 1
        #     logger.bind(tag=TAG).info(f"[sendAudioMessage] Finished sending {packet_index} packets for index {text_index}")
        # else:
        #     logger.bind(tag=TAG).warning(f"[sendAudioMessage] No Opus packets to send for index {text_index}")
        await _send_audio(context, audios)

        # 发送句子结束信号
        logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending sentence_end for index {text_index}")
        await context.channel.send_message(sentence_end_msg)
        # await context.channel.send_message(end_msg)

        # 检查是否是最后一个文本片段
        if context.llm_finish_task and context.tts_last_text_index == text_index:
            logger.bind(tag=TAG).info(f"[sendAudioMessage] Sending final end signal as index {text_index} is the last.")
            await asyncio.sleep(0.01) # Ensure empty packet is sent before final JSON

            # 发送最后暂停信号
            await context.channel.send_message(sentence_stop_msg)
            if context.close_after_chat:
                logger.bind(tag=TAG).info("[sendAudioMessage] Closing contextection after chat.")
                await context.close()
    except Exception as e:
        logger.bind(tag=TAG).error(f"[sendAudioMessage] Error sending audio for index {text_index}: {e}", exc_info=True)
        # Optionally try to send an error message to client
        try:
            # Use MessageFactory for error message
            error_text = f"Error sending audio for index {text_index}"
            error_msg = MessageFactory.create_error_message(session_id, text_index, error_text)
            await context.channel.send_message(error_msg)
        except Exception as send_err:
            logger.bind(tag=TAG).error(f"[sendAudioMessage] Failed to send error message to client: {send_err}")
        # Maybe clear status on error too?
        context.clearSpeakStatus()

    logger.bind(tag=TAG).info(f"[sendAudioMessage] Finished processing index {text_index}")


# 播放音频
async def _send_audio(context: 'HandlerContext', audios):
    # num_packets = len(audios) if isinstance(audios, list) else 0
    # logger.bind(tag=TAG).info(f"[sendAudioMessage] Starting for index {text_index}, packets: {num_packets}, text: '{text}'")
    if isinstance(audios, list) and audios:
        packet_index = 0
        for packet in audios:
            if context.client_abort:
                # logger.bind(tag=TAG).warning(f"[sendAudioMessage] Client aborted during Opus stream for index {text_index}.")
                break
            if packet:
                # logger.bind(tag=TAG).debug(f"[sendAudioMessage] Sending packet {packet_index + 1}/{num_packets} for index {text_index}, size: {len(packet)}")
                await context.channel.send_bytes(packet)
                # await asyncio.sleep(0.01)  # 短暂休眠，避免发送过快，给网络和客户端处理时间
                packet_index += 1
            else:
                # logger.bind(tag=TAG).warning(f"[sendAudioMessage] Skipping empty packet {packet_index + 1}/{num_packets} for index {text_index}")
                packet_index += 1

# async def _send_audio(context: 'HandlerContext', audios):
#     # 流控参数优化
#     frame_duration = 60  # 帧时长（毫秒），匹配 Opus 编码
#     start_time = time.perf_counter()
#     play_position = 0

#     # 预缓冲：发送前 3 帧
#     pre_buffer = min(3, len(audios))
#     for i in range(pre_buffer):
#         await context.channel.send_bytes(audios[i])

#     # 正常播放剩余帧
#     for opus_packet in audios[pre_buffer:]:
#         if context.client_abort:
#             logger.bind(tag=TAG).info("Client aborted during audio send.")
#             return

#         # 计算预期发送时间
#         expected_time = start_time + (play_position / 1000)
#         current_time = time.perf_counter()
#         delay = expected_time - current_time
#         if delay > 0:
#             await asyncio.sleep(delay)

#         await context.channel.send_bytes(opus_packet)

#         play_position += frame_duration


async def send_tts_message(context: 'HandlerContext', state, text=None):
    """发送 TTS 状态消息"""
    # Use MessageFactory for TTS state message
    message = MessageFactory.create_tts_state_message(context.session_id, state, text)
    # 如果 text 存在，则发送文本
    if text is not None:
        message["text"] = text
    
    # TTS播放结束
    if state == MessageFactory.TTS_STATE_STOP: # Use constant
        tts_notify = context.config.get("enable_stop_tts_notify", False)
        if tts_notify:
            stop_tts_notify_voice = context.config.get(
                "stop_tts_notify_voice", "config/assets/tts_notify.mp3"
            )
            audios, duration = context.tts.audio_to_opus_data(stop_tts_notify_voice)
            await _send_audio(context, audios)
        context.clearSpeakStatus()
    # 发送 TTS 状态消息
    await context.channel.send_message(message)


async def send_stt_message(context: 'HandlerContext', text):
    """发送 STT 状态消息"""
    stt_text = get_string_no_punctuation_or_emoji(text)
    # 发送 STT 消息
    stt_message = MessageFactory.create_stt_message(context.session_id, stt_text)
    await context.channel.send_message(stt_message)

    # Use MessageFactory for LLM thinking message
    llm_thinking_message = MessageFactory.create_llm_thinking_message(context.session_id)
    await context.channel.send_message(llm_thinking_message)

    # Use MessageFactory constant for state
    await send_tts_message(context, MessageFactory.TTS_STATE_START)
