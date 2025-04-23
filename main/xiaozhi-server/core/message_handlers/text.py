# New file: main/xiaozhi-server/core/message_handlers/text.py
import json
import asyncio
from config.logger import setup_logging
from core.handle.abortHandler import handleAbortMessage # Keep old import for now
from ..handle.helloHandler import handleHelloMessage # Keep old import for now
from ..utils.util import remove_punctuation_and_length
from ..handle.receiveAudioHandler import startToChat, handleAudioMessage # Keep old import for now
from ..handle.sendAudioHandler import send_stt_message, send_tts_message # Keep old import for now
from ..handle.iotHandler import handleIotDescriptors, handleIotStatus # Keep old import for now
from ..channels.interface import ICommunicationChannel # Keep old import for now

from .base import BaseMessageHandler
from .context import HandlerContext # Import HandlerContext


TAG = __name__
logger = setup_logging()

class TextMessageHandler(BaseMessageHandler):
    """Handles incoming text messages, adapted from original handleTextMessage."""

    async def handle(self, message: str, context: HandlerContext):
        """处理文本消息"""
        logger.bind(tag=TAG).info(f"收到文本消息：{message}")
        # TODO: Replace conn and channel with context attributes
        # Access dependencies via context, e.g., context.channel, context.logger, context.config etc.
        # The original 'conn' object had many attributes. These need to be added to HandlerContext.
        # Example: context.channel replaces the original 'channel' parameter.
        # Example: context.client_listen_mode replaces conn.client_listen_mode
        # Example: context.asr_audio replaces conn.asr_audio

        channel = context.channel # Assume context has a 'channel' attribute of type ICommunicationChannel
        conn = context # Treat context as the source of 'conn' attributes for now

        try:
            msg_json = json.loads(message)
            if isinstance(msg_json, int):
                logger.bind(tag=TAG).debug(f"Received integer, sending raw string: {message}")
                await channel.send_raw_string(message) # Use channel from context
                return
            msg_type = msg_json.get("type")
            if msg_type == "hello":
                # await handleHelloMessage(conn, channel) # Needs conn and channel from context
                await handleHelloMessage(context, context.channel) # Pass context and its channel
            elif msg_type == "abort":
                # await handleAbortMessage(conn, channel) # Needs conn and channel from context
                await handleAbortMessage(context, context.channel) # Pass context and its channel
            elif msg_type == "listen":
                if "mode" in msg_json:
                    conn.client_listen_mode = msg_json["mode"] # Needs context.client_listen_mode
                    logger.bind(tag=TAG).debug(f"客户端拾音模式：{conn.client_listen_mode}")
                state = msg_json.get("state")
                if state == "start":
                    conn.client_have_voice = True # Needs context.client_have_voice
                    conn.client_voice_stop = False # Needs context.client_voice_stop
                elif state == "stop":
                    conn.client_have_voice = True # Needs context.client_have_voice
                    conn.client_voice_stop = True # Needs context.client_voice_stop
                    # Immediately update the shared ConnectionHandler state as well
                    if hasattr(context, 'conn_handler') and context.conn_handler:
                         context.conn_handler.client_voice_stop = True
                         logger.bind(tag=TAG).debug("Updated conn_handler.client_voice_stop=True")
                    else:
                         logger.bind(tag=TAG).warning("Cannot update conn_handler state: conn_handler not found in context.")

                    logger.bind(tag=TAG).debug(f"Set context.client_voice_stop=True. Value: {context.client_voice_stop}")
                    logger.bind(tag=TAG).debug(f"Received listen stop signal. Buffer size: {len(context.asr_audio)}")
                    # Trigger audio processing if buffer has content
                    if len(context.asr_audio) > 0:
                        logger.bind(tag=TAG).info("Listen stop received with non-empty buffer. Triggering ASR processing.")
                        try:
                            # Simulate empty audio message to trigger AudioHandler processing
                            await context.conn_handler._route_message(b"")
                        except Exception as trigger_err:
                            logger.bind(tag=TAG).error(f"Error triggering audio handler on stop: {trigger_err}", exc_info=True)
                    else:
                        logger.bind(tag=TAG).debug("Listen stop received with empty buffer. No ASR trigger needed.")
                elif state == "detect":
                    conn.asr_server_receive = False # Needs context.asr_server_receive
                    conn.client_have_voice = False # Needs context.client_have_voice
                    conn.asr_audio.clear() # Needs context.asr_audio
                    if "text" in msg_json:
                        text = msg_json["text"]
                        _, text_norm = remove_punctuation_and_length(text) # Keep utility function

                        # Needs context.config
                        is_wakeup_words = text_norm in conn.config.get("wakeup_words", [])
                        enable_greeting = conn.config.get("enable_greeting", True)

                        if is_wakeup_words and not enable_greeting:
                            # Needs context for send functions
                            # await send_stt_message(conn, text)
                            # await send_tts_message(conn, "stop", None)
                            await send_stt_message(context, text)
                            await send_tts_message(context, "stop", None)
                        else:
                            # Needs context for startToChat
                            logger.bind(tag=TAG).debug(f"Calling startToChat for text: '{text}'")
                            try:
                                # await startToChat(conn, text)
                                await startToChat(context, text) # Pass context
                                logger.bind(tag=TAG).debug(f"startToChat finished for text: '{text}'")
                            except Exception as chat_err:
                                logger.bind(tag=TAG).error(f"Error calling or awaiting startToChat: {chat_err}", exc_info=True)
            elif msg_type == "iot":
                # Needs context for iot handlers
                if "descriptors" in msg_json:
                    # asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
                    asyncio.create_task(handleIotDescriptors(context, msg_json["descriptors"]))
                if "states" in msg_json:
                    # asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
                    asyncio.create_task(handleIotStatus(context, msg_json["states"]))
        except json.JSONDecodeError:
            logger.bind(tag=TAG).warning(f"Received non-JSON message, sending raw string: {message}")
            await channel.send_raw_string(message) # Use channel from context
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error handling text message: {e}", exc_info=True)
            # Optionally send an error message back to the client
            try:
                await channel.send_json({"type": "error", "message": "Internal server error handling text message."})
            except Exception as send_error:
                logger.bind(tag=TAG).error(f"Failed to send error message to client: {send_error}")

# Keep helper functions within the module for now, or move them later
# These functions currently rely on 'conn' which needs to become 'context'

async def handleHelloMessage(context: HandlerContext, channel: ICommunicationChannel):
    """处理 hello 消息 (adapted for context)"""
    logger.bind(tag=TAG).info("处理 hello 消息")
    context.client_speak = False
    context.client_speak_last_time = 0.0
    await channel.send_json({"type": "hello", "message": "ok"})

async def handleAbortMessage(context: HandlerContext, channel: ICommunicationChannel):
    """处理 abort 消息 (adapted for context)"""
    logger.bind(tag=TAG).info("处理 abort 消息")
    context.client_abort = True
    context.client_speak = False
    context.client_speak_last_time = 0.0
    await channel.send_json({"type": "abort", "message": "ok"})

# Note: send_stt_message, send_tts_message, startToChat, handleAudioMessage,
# handleIotDescriptors, handleIotStatus are still imported from old locations.
# They also need to be adapted to use context if called directly.
# Ideally, logic from these should be moved into relevant handlers or services
# accessible via the context (e.g., context.dispatcher, context.iot_service).
# For now, we pass 'context' where 'conn' was expected, assuming attributes match. 