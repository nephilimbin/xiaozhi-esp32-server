import typing

if typing.TYPE_CHECKING:
    from core.message_handlers.context import HandlerContext

TAG = "MessageModels"


class MessageFactory:
    TYPE_TTS = "tts"
    TYPE_ERROR = "error"
    TYPE_STT = "stt"
    TYPE_LLM = "llm"

    # TTS States
    TTS_STATE_START = "start"
    TTS_STATE_END = "end"
    TTS_STATE_STOP = "stop" # Assuming 'stop' might be used elsewhere or in future
    TTS_STATE_SENTENCE_START = "sentence_start"
    TTS_STATE_SENTENCE_END = "sentence_end"

    # LLM Content (Example)
    LLM_THINKING_TEXT = "😊让我思考下"
    LLM_THINKING_EMOTION = "happy"


    @staticmethod
    def create_tts_start_message(session_id: str, index: int, text: str | None = None) -> dict:
        """创建 TTS 开始消息"""
        msg = {
            "type": MessageFactory.TYPE_TTS,
            "state": MessageFactory.TTS_STATE_START,
            "session_id": session_id,
            "index": index,
        }
        # 只有第一个语音片段需要传递文本
        if text is not None:
            msg["text"] = text
        else:
            msg["text"] = "" # 确保 text 字段存在
        return msg

    @staticmethod
    def create_tts_end_message(session_id: str, index: int) -> dict:
        """创建 TTS 结束消息"""
        return {
            "type": MessageFactory.TYPE_TTS,
            "state": MessageFactory.TTS_STATE_END,
            "session_id": session_id,
            "index": index,
        }

    @staticmethod
    def create_tts_state_message(session_id: str, state: str, text: str | None = None) -> dict:
        """创建 TTS 状态消息 (通用)"""
        message = {
            "type": MessageFactory.TYPE_TTS,
            "state": state,
            "session_id": session_id,
        }
        if text is not None:
            message["text"] = text
        return message


    @staticmethod
    def create_error_message(session_id: str, index: int, error_text: str) -> dict:
        """创建错误消息"""
        return {
            "type": MessageFactory.TYPE_ERROR,
            "message": error_text,
            "session_id": session_id,
            "index": index,
        }


    @staticmethod
    def create_stt_message(session_id: str, text: str) -> dict:
        """创建 STT 消息"""
        return {
            "type": MessageFactory.TYPE_STT,
            "text": text,
            "session_id": session_id,
        }

    @staticmethod
    def create_llm_thinking_message(session_id: str) -> dict:
        """创建 LLM 思考中消息"""
        return {
            "type": MessageFactory.TYPE_LLM,
            "text": MessageFactory.LLM_THINKING_TEXT,
            "emotion": MessageFactory.LLM_THINKING_EMOTION,
            "session_id": session_id,
        } 
        
        
        