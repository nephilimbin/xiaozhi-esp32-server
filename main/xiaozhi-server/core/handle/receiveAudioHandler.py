from config.logger import setup_logging
import time
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandler import send_stt_message
from core.handle.intentHandler import handle_user_intent

TAG = __name__
logger = setup_logging()


async def handleAudioMessage(context, audio):
    try:
        if not context.asr_server_receive:
            logger.bind(tag=TAG).debug("前期数据处理中，暂停接收")
            return
        if context.client_listen_mode == "auto":
            have_voice = context.vad.is_vad(context, audio)
        else:
            have_voice = context.client_have_voice

        # 如果本次没有声音，本段也没声音，就把声音丢弃了
        if not have_voice and not context.client_have_voice:
            await no_voice_close_connect(context)
            context.asr_audio.append(audio)
            return
        context.client_no_voice_last_time = 0.0
        context.asr_audio.append(audio)
        # 如果本段有声音，且已经停止了
        if context.client_voice_stop:
            context.client_abort = False
            context.asr_server_receive = False
            # 音频太短了，无法识别
            if len(context.asr_audio) < 15:
                context.asr_server_receive = True
            else:
                text, file_path = await context.asr.speech_to_text(
                    list(context.asr_audio), context.session_id
                )
                logger.bind(tag=TAG).info(f"识别文本: {text}")
                text_len, _ = remove_punctuation_and_length(text)
                if text_len > 0:
                    await startToChat(context, text)
                else:
                    context.asr_server_receive = True
            context.asr_audio.clear()
            context.reset_vad_states()
    except Exception as e:
        logger.bind(tag=TAG).error(f"处理音频消息时发生错误: {e}")
        context.asr_server_receive = True


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
