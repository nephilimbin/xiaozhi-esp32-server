from config.logger import setup_logging
import time
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandler import send_stt_message
from core.handle.intentHandler import handle_user_intent

TAG = __name__
logger = setup_logging()


async def handleAudioMessage(context, audio):
    conn = context  # Temporary alias
    if not conn.asr_server_receive:
        logger.bind(tag=TAG).debug(f"前期数据处理中，暂停接收")
        return
    if conn.client_listen_mode == "auto":
        have_voice = conn.vad.is_vad(conn.conn_handler, audio)
    else:
        have_voice = conn.client_have_voice

    # 如果本次没有声音，本段也没声音，就把声音丢弃了
    if have_voice == False and conn.client_have_voice == False:
        await no_voice_close_connect(context)
        context.asr_audio.append(audio)
        return
    context.client_no_voice_last_time = 0.0
    context.asr_audio.append(audio)
    # 如果本段有声音，且已经停止了
    if conn.client_voice_stop:
        conn.client_abort = False
        conn.asr_server_receive = False
        # 音频太短了，无法识别
        if len(conn.asr_audio) < 15:
            conn.asr_server_receive = True
        else:
            text, file_path = await conn.asr.speech_to_text(
                list(conn.asr_audio), conn.session_id
            )
            logger.bind(tag=TAG).info(f"识别文本: {text}")
            text_len, _ = remove_punctuation_and_length(text)
            if text_len > 0:
                await startToChat(context, text)
            else:
                conn.asr_server_receive = True
        conn.asr_audio.clear()
        conn.reset_vad_states()


async def startToChat(context, text):
    # 首先进行意图分析
    intent_handled = await handle_user_intent(context, text)

    if intent_handled:
        # 如果意图已被处理，不再进行聊天
        context.asr_server_receive = True
        return

    # 意图未被处理，继续常规聊天流程
    await send_stt_message(context, text)
    if context.use_function_call_mode:
        # 使用支持function calling的聊天方法
        context.executor.submit(context.chat_with_function_calling, text)
        logger.bind(tag=TAG).debug(
            f"Submitted chat_with_function_calling task for: {text}"
        )
    else:
        context.executor.submit(context.chat, text)
        logger.bind(tag=TAG).debug(f"Submitted chat task for: {text}")


async def no_voice_close_connect(context):
    if context.client_no_voice_last_time == 0.0:
        context.client_no_voice_last_time = time.time() * 1000
    else:
        no_voice_time = time.time() * 1000 - context.client_no_voice_last_time
        close_connection_no_voice_time = context.config.get(
            "close_connection_no_voice_time", 120
        )
        if (
            not context.close_after_chat
            and no_voice_time > 1000 * close_connection_no_voice_time
        ):
            context.close_after_chat = True
            context.client_abort = False
            context.asr_server_receive = False
            prompt = (
                "请你以“时间过得真快”为开头，用富有感情、依依不舍的话来结束这场对话吧。"
            )
            await startToChat(context, prompt)
