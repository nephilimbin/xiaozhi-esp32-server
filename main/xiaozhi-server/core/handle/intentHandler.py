from config.logger import setup_logging
import json
import uuid
from core.handle.sendAudioHandler import send_stt_message
from core.handle.helloHandler import checkWakeupWords
from core.utils.util import remove_punctuation_and_length
from core.utils.dialogue import Message

TAG = __name__
logger = setup_logging()


async def handle_user_intent(context, text):
    try:
        # 检查是否有明确的退出命令
        if await check_direct_exit(context, text):
            return True
        # 检查是否是唤醒词
        if await checkWakeupWords(context, text):
            return True

        if context.use_function_call_mode:
            # 使用支持function calling的聊天方法,不再进行意图分析
            return False
        # 使用LLM进行意图分析
        intent_result = await analyze_intent_with_llm(context, text)
        if not intent_result:
            return False
        # 处理各种意图
    except Exception as e:
        logger.bind(tag=TAG).error(f"意图处理失败: {e}")
        return False
    return await process_intent_result(context, intent_result, text)


async def check_direct_exit(context, text):
    """检查是否有明确的退出命令"""
    _, text = remove_punctuation_and_length(text)
    cmd_exit = context.cmd_exit
    for cmd in cmd_exit:
        if text == cmd:
            logger.bind(tag=TAG).info(f"识别到明确的退出命令: {text}")
            await send_stt_message(context, text)
            await context.close()
            return True
    return False


async def analyze_intent_with_llm(context, text):
    """使用LLM分析用户意图"""
    if not hasattr(context, "intent") or not context.intent:
        logger.bind(tag=TAG).warning("意图识别服务未初始化")
        return None

    # 对话历史记录
    dialogue = context.dialogue
    try:
        intent_result = await context.intent.detect_intent(context, dialogue.dialogue, text)
        return intent_result
    except Exception as e:
        logger.bind(tag=TAG).error(f"意图识别失败: {str(e)}")

    return None


async def process_intent_result(context, intent_result, original_text):
    """处理意图识别结果"""
    try:
        # 尝试将结果解析为JSON
        intent_data = json.loads(intent_result)

        # 检查是否有function_call
        if "function_call" in intent_data:
            # 直接从意图识别获取了function_call
            logger.bind(tag=TAG).debug(
                f"检测到function_call格式的意图结果: {intent_data['function_call']['name']}"
            )
            function_name = intent_data["function_call"]["name"]
            if function_name == "continue_chat":
                return False

            function_args = None
            if "arguments" in intent_data["function_call"]:
                function_args = intent_data["function_call"]["arguments"]
            # 确保参数是字符串格式的JSON
            if isinstance(function_args, dict):
                function_args = json.dumps(function_args)

            function_call_data = {
                "name": function_name,
                "id": str(uuid.uuid4().hex),
                "arguments": function_args,
            }

            await send_stt_message(context, original_text)

            # 使用executor执行函数调用和结果处理
            def process_function_call():
                context.dialogue.put(Message(role="user", content=original_text))
                result = context.func_handler.handle_llm_function_call(
                    context, function_call_data
                )
                if result and function_name != "play_music":
                    # 获取当前最新的文本索引
                    text = result.response
                    if text is None:
                        text = result.result
                    if text is not None:
                        text_index = (
                            context.tts_last_text_index + 1
                            if hasattr(context, "tts_last_text_index")
                            else 0
                        )
                        context.recode_first_last_text(text, text_index)
                        future = context.executor.submit(
                            context.speak_and_play, text, text_index
                        )
                        context.llm_finish_task = True
                        context.tts_queue.put(future)
                        context.dialogue.put(Message(role="assistant", content=text))

            # 将函数执行放在线程池中
            context.executor.submit(process_function_call)
            return True
        return False
    except json.JSONDecodeError as e:
        logger.bind(tag=TAG).error(f"处理意图结果时出错: {e}")
        return False


def extract_text_in_brackets(s):
    """
    从字符串中提取中括号内的文字

    :param s: 输入字符串
    :return: 中括号内的文字，如果不存在则返回空字符串
    """
    left_bracket_index = s.find("[")
    right_bracket_index = s.find("]")

    if (
        left_bracket_index != -1
        and right_bracket_index != -1
        and left_bracket_index < right_bracket_index
    ):
        return s[left_bracket_index + 1 : right_bracket_index]
    else:
        return ""
