# New file: main/xiaozhi-server/core/message_handlers/audio.py
import time
from config.logger import setup_logging
from core.utils.util import remove_punctuation_and_length
from core.handle.sendAudioHandler import send_stt_message
from core.handle.intentHandler import handle_user_intent
from core.message_handlers.base import BaseMessageHandler
import typing
if typing.TYPE_CHECKING:
    from core.message_handlers.context import HandlerContext

TAG = __name__
logger = setup_logging()

class AudioMessageHandler(BaseMessageHandler):
    """Handles incoming audio messages/data, adapted from original handleAudioMessage."""

    async def handle(self, message, context: 'HandlerContext'):
        """Handles raw audio bytes using context."""
        try:
            audio = message
            # logger.bind(tag=TAG).debug(f"[handle] Inside handle. Received audio chunk size: {len(audio)}") 

            # Directly use context attributes
            if not context.asr_server_receive:
                logger.bind(tag=TAG).debug("[handle] Exiting early: context.asr_server_receive is False.") 
                return
            # Default value
            have_voice = False 
            try:
                # Use context attributes and pass context/conn_handler to dependencies if needed
                if context.client_listen_mode == "auto":
                    logger.bind(tag=TAG).debug("[handle] Mode auto, calling VAD...") # Log VAD call
                    # Assuming vad.is_vad expects the handler/connection object for some reason
                    have_voice = context.vad.is_vad(context, audio)
                    logger.bind(tag=TAG).debug(f"[handle] VAD result: {have_voice}") # Log VAD result
                else:
                    have_voice = context.client_have_voice
                    logger.bind(tag=TAG).debug(f"[handle] Mode manual, have_voice from context: {have_voice}") 

            except Exception as vad_err:
                logger.bind(tag=TAG).error(f"[handle] Error during VAD check: {vad_err}", exc_info=True)
                # Decide how to proceed, maybe assume no voice or re-raise? For now, log and continue

            logger.bind(tag=TAG).debug(f"[handle] Checking have_voice ({have_voice}) and context.client_have_voice ({context.client_have_voice})") # Log check
            # 如果本次没有声音，本段也没声音，就把声音丢弃了
            if not have_voice and not context.client_have_voice:
                logger.bind(tag=TAG).debug(f"[handle] Exiting early: No voice detected (VAD={have_voice}, client_state={context.client_have_voice}).") # Log check
                # Avoid calling no_voice_close_connect here if client explicitly started sending
                # self.asr_audio buffer is likely empty anyway if VAD says no voice on first chunks.
                # Let's just append and rely on no_voice_close_connect being called by subsequent silent chunks if needed.
                await self.no_voice_close_connect(context)
                context.asr_audio.append(audio)
                return

            # If we reach here, VAD or client state indicates voice is present
            context.client_no_voice_last_time = 0.0
            context.asr_audio.append(audio)
            logger.bind(tag=TAG).debug(f"[handle] Appended audio. Buffer size: {len(context.asr_audio)}") # Log append

            # Check if client signaled stop
            logger.bind(tag=TAG).debug(f"[handle] Checking context.client_voice_stop: {context.client_voice_stop}") # Log before check
            # 如果本段有声音，且已经停止了
            if context.client_voice_stop:
                logger.bind(tag=TAG).debug("[handle] context.client_voice_stop is True. Starting ASR processing.") # Log processing start
                context.client_abort = False
                context.asr_server_receive = False
                # 音频太短了，无法识别
                if len(context.asr_audio) < 15:
                    context.asr_server_receive = True
                else:
                    # Assuming asr.speech_to_text can accept context or specific attributes
                    # Pass necessary context attributes like session_id
                    # Pass the audio data (convert deque to list if required by the ASR method)
                    try:
                        logger.bind(tag=TAG).debug(f"Sending {len(context.asr_audio)} audio frames to ASR.")
                        text, file_path = await context.asr.speech_to_text(
                            list(context.asr_audio), context.session_id # Pass list and session_id from context
                        )
                        logger.bind(tag=TAG).info(f"识别文本: {text}")
                        text_len, _ = remove_punctuation_and_length(text)
                        if text_len > 0:
                            await self.startToChat(context, text)
                        else:
                            # No valid text recognized
                            context.asr_server_receive = True
                    except Exception as asr_err:
                        logger.bind(tag=TAG).error(f"ASR processing error: {asr_err}", exc_info=True)
                        context.asr_server_receive = True # Allow receiving new audio after error
                    finally:
                        # Clear audio buffer regardless of ASR success/failure
                        context.asr_audio.clear()
                        # Use context's reset method
                        context.reset_vad_states()
        except Exception as e:
            logger.bind(tag=TAG).error(f"AudioMessageHandler 处理错误: {e}", exc_info=True)

    async def startToChat(self, context: 'HandlerContext', text):
        """Initiates the chat flow after STT (adapted for context)"""
        logger.bind(tag=TAG).debug(f"[startToChat] Handling intent for: '{text}'")
        intent_handled = await handle_user_intent(context, text) 

        if intent_handled:
            logger.bind(tag=TAG).debug(f"[startToChat] Intent handled, skipping chat for: '{text}'")
            context.asr_server_receive = True
            return

        logger.bind(tag=TAG).debug(f"[startToChat] Sending STT message: '{text}'")
        await send_stt_message(context, text)

        # Submit chat task using context.conn_handler methods
        if context.use_function_call_mode:
            logger.bind(tag=TAG).debug(f"[startToChat] Submitting function calling chat task for: '{text}'")
            context.executor.submit(context.chat_with_function_calling, text)
        else:
            logger.bind(tag=TAG).debug(f"[startToChat] Submitting standard chat task for: '{text}'")
            context.executor.submit(context.chat, text)

        # Ensure ASR is ready after submitting the task
        context.asr_server_receive = True
        logger.bind(tag=TAG).debug("[startToChat] Set asr_server_receive=True")

    async def no_voice_close_connect(self, context: 'HandlerContext'):
        """Handles logic for closing connection due to prolonged silence (uses context)"""

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
                logger.bind(tag=TAG).warning(f"Closing connection due to {close_connection_no_voice_time}s silence.")
                context.close_after_chat = True
                context.client_abort = False
                context.asr_server_receive = False
                prompt = '''请你以"时间过得真快"为开头，用富有感情、依依不舍的话来结束这场对话吧。'''
                await self.startToChat(context, prompt)



