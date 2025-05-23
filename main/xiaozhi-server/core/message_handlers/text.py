# New file: main/xiaozhi-server/core/message_handlers/text.py
import json
import asyncio
from config.logger import setup_logging
from core.handle.abortHandler import handleAbortMessage  # Keep old import for now
from core.handle.helloHandler import handleHelloMessage  # Keep old import for now
from core.utils.util import remove_punctuation_and_length
# from core.handle.receiveAudioHandler import (
#     startToChat,
# ) 
from core.handle.sendAudioHandler import (
    send_stt_message,
    send_tts_message,
)  
from core.handle.iotHandler import (
    handleIotDescriptors,
    handleIotStatus,
)  
from core.channels.interface import ICommunicationChannel 

from core.message_handlers.base import BaseMessageHandler


TAG = __name__
logger = setup_logging()


class TextMessageHandler(BaseMessageHandler):
    """Handles incoming text messages, adapted from original handleTextMessage."""

    async def handle(self, message, context):
        """处理文本消息"""
        logger.bind(tag=TAG).info(f"收到文本消息：{message}")
        # TODO: Replace conn and channel with context attributes
        # Access dependencies via context, e.g., context.channel, context.logger, context.config etc.
        # The original 'conn' object had many attributes. These need to be added to HandlerContext.
        # Example: context.channel replaces the original 'channel' parameter.
        # Example: context.client_listen_mode replaces conn.client_listen_mode
        # Example: context.asr_audio replaces conn.asr_audio

        channel = (
            context.channel
        )  # Assume context has a 'channel' attribute of type ICommunicationChannel
        # conn = context  # Treat context as the source of 'conn' attributes for now

        try:
            msg_json = json.loads(message)
            if isinstance(msg_json, int):
                logger.bind(tag=TAG).debug(
                    f"Received integer, sending raw string: {message}"
                )
                await channel.send_raw_string(message)  # Use channel from context
                return
            msg_type = msg_json.get("type")
            if msg_type == "hello":
                # await handleHelloMessage(conn, channel) # Needs conn and channel from context
                await handleHelloMessage(
                    context, context.channel
                )  # Pass context and its channel
            elif msg_type == "abort":
                # await handleAbortMessage(conn, channel) # Needs conn and channel from context
                await handleAbortMessage(
                    context, context.channel
                )  # Pass context and its channel
            elif msg_type == "listen":
                if "mode" in msg_json:
                    # conn.client_listen_mode = msg_json[
                    context.client_listen_mode = msg_json[
                        "mode"
                    ]  # Needs context.client_listen_mode
                    logger.bind(tag=TAG).debug(
                        f"客户端拾音模式：{context.client_listen_mode}"
                    )
                state = msg_json.get("state")
                if state == "start":
                    context.client_have_voice = True  # Needs context.client_have_voice
                    context.client_voice_stop = False  # Needs context.client_voice_stop
                elif state == "stop":
                    context.client_have_voice = True  # Needs context.client_have_voice
                    context.client_voice_stop = True  # Needs context.client_voice_stop
                    # Immediately update the shared ConnectionHandler state as well
                    logger.bind(tag=TAG).debug(
                        f"Set context.client_voice_stop=True. Value: {context.client_voice_stop}"
                    )
                    logger.bind(tag=TAG).debug(
                        f"Received listen stop signal. Buffer size: {len(context.asr_audio)}"
                    )
                    # Trigger audio processing if buffer has content
                    if len(context.asr_audio) > 0:
                        logger.bind(tag=TAG).info(
                            "Listen stop received with non-empty buffer. Triggering ASR processing."
                        )
                        try:
                            # Simulate empty audio message to trigger AudioHandler processing
                            await context._route_message(b"")
                        except Exception as trigger_err:
                            logger.bind(tag=TAG).error(
                                f"Error triggering audio handler on stop: {trigger_err}",
                                exc_info=True,
                            )
                    else:
                        logger.bind(tag=TAG).debug(
                            "Listen stop received with empty buffer. No ASR trigger needed."
                        )
                elif state == "detect":
                    context.asr_server_receive = False
                    context.client_have_voice = False
                    context.asr_audio.clear()
                    if "text" in msg_json:
                        text = msg_json["text"]
                        _, text_norm = remove_punctuation_and_length(
                            text
                        )  # Keep utility function

                        # Needs context.config
                        is_wakeup_words = text_norm in context.config.get(
                            "wakeup_words", []
                        )
                        enable_greeting = context.config.get("enable_greeting", True)

                        if is_wakeup_words and not enable_greeting:
                            await send_stt_message(context, text)
                            await send_tts_message(context, "stop", None)
                        else:
                            # Needs context for startToChat
                            logger.bind(tag=TAG).debug(
                                f"Calling startToChat for text: '{text}'"
                            )
                            try:
                                # await startToChat(conn, text)
                                await context.router.audio_handler.startToChat(context, text)  # Pass context
                                logger.bind(tag=TAG).debug(
                                    f"startToChat finished for text: '{text}'"
                                )
                            except Exception as chat_err:
                                logger.bind(tag=TAG).error(
                                    f"Error calling or awaiting startToChat: {chat_err}",
                                    exc_info=True,
                                )
            elif msg_type == "iot":
                # Needs context for iot handlers
                if "descriptors" in msg_json:
                    # asyncio.create_task(handleIotDescriptors(conn, msg_json["descriptors"]))
                    asyncio.create_task(
                        handleIotDescriptors(context, msg_json["descriptors"])
                    )
                if "states" in msg_json:
                    # asyncio.create_task(handleIotStatus(conn, msg_json["states"]))
                    asyncio.create_task(handleIotStatus(context, msg_json["states"]))
        except json.JSONDecodeError:
            logger.bind(tag=TAG).warning(
                f"Received non-JSON message, sending raw string: {message}"
            )
            await channel.send_raw_string(message)  # Use channel from context
        except Exception as e:
            logger.bind(tag=TAG).error(
                f"Error handling text message: {e}", exc_info=True
            )
            # Optionally send an error message back to the client
            try:
                await channel.send_json(
                    {
                        "type": "error",
                        "message": "Internal server error handling text message.",
                    }
                )
            except Exception as send_error:
                logger.bind(tag=TAG).error(
                    f"Failed to send error message to client: {send_error}"
                )


# Keep helper functions within the module for now, or move them later
# These functions currently rely on 'conn' which needs to become 'context'


async def handleHelloMessage(context, channel: ICommunicationChannel):
    """处理 hello 消息 (adapted for context)"""
    logger.bind(tag=TAG).info("处理 hello 消息")
    context.client_speak = False
    context.client_speak_last_time = 0.0
    await channel.send_json({"type": "hello", "message": "ok"})


async def handleAbortMessage(context, channel: ICommunicationChannel):
    """处理 abort 消息 (adapted for context)"""
    logger.bind(tag=TAG).info("处理 abort 消息")
    context.client_abort = True
    context.client_speak = False
    context.client_speak_last_time = 0.0
    await channel.send_json({"type": "abort", "message": "ok"})

