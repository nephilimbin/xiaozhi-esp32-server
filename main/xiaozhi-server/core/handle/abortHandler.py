import json
from config.logger import setup_logging
# Import the interface from the new location
from ..channels.interface import ICommunicationChannel

TAG = __name__
logger = setup_logging()


# Add channel parameter
async def handleAbortMessage(conn, channel: ICommunicationChannel):
    logger.bind(tag=TAG).info("Abort message received")
    # 设置成打断状态，会自动打断llm、tts任务
    conn.client_abort = True # Keep state management with conn for now
    # 打断客户端说话状态
    # Use the channel interface to send the message
    await channel.send_json({"type": "tts", "state": "stop", "session_id": conn.session_id})
    conn.clearSpeakStatus() # Keep state management with conn for now
    logger.bind(tag=TAG).info("Abort message received-end")
