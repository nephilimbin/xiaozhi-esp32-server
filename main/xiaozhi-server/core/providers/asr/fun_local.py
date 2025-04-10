import time
import wave
import os
import sys
import io
from config.logger import setup_logging
from typing import Optional, Tuple, List
import uuid
import opuslib_next
from core.providers.asr.base import ASRProviderBase

from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess

TAG = __name__
logger = setup_logging()


# 捕获标准输出
class CaptureOutput:
    def __enter__(self):
        self._output = io.StringIO()
        self._original_stdout = sys.stdout
        sys.stdout = self._output

    def __exit__(self, exc_type, exc_value, traceback):
        sys.stdout = self._original_stdout
        self.output = self._output.getvalue()
        self._output.close()

        # 将捕获到的内容通过 logger 输出
        if self.output:
            logger.bind(tag=TAG).info(self.output.strip())


class ASRProvider(ASRProviderBase):
    def __init__(self, config: dict, delete_audio_file: bool):
        model_dir_relative = config.get("model_dir")
        output_dir_relative = config.get("output_dir")
        self.delete_audio_file = delete_audio_file

        # 获取当前文件的绝对路径
        current_file_path = os.path.abspath(__file__)
        # 推算应用根目录 (main/xiaozhi-server)
        app_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(current_file_path)))
        )

        # 计算模型和输出目录的绝对路径
        self.model_dir_absolute = os.path.join(app_root, model_dir_relative)
        self.output_dir_absolute = os.path.join(app_root, output_dir_relative)

        logger.bind(tag=TAG).info(f"App root: {app_root}")
        logger.bind(tag=TAG).info(
            f"Calculated absolute model path: {self.model_dir_absolute}"
        )
        logger.bind(tag=TAG).info(
            f"Calculated absolute output path: {self.output_dir_absolute}"
        )

        # 确保输出目录存在
        os.makedirs(self.output_dir_absolute, exist_ok=True)
        with CaptureOutput():
            self.model = AutoModel(
                model=self.model_dir_absolute,  # 使用动态计算的绝对路径
                vad_kwargs={"max_single_segment_time": 30000},
                disable_update=True,
                hub="hf",
                # device="cuda:0",  # 启用GPU加速
            )

    def save_audio_to_file(self, opus_data: List[bytes], session_id: str) -> str:
        """将Opus音频数据解码并保存为WAV文件"""
        file_name = f"asr_{session_id}_{uuid.uuid4()}.wav"
        # 使用绝对路径保存文件
        file_path = os.path.join(self.output_dir_absolute, file_name)

        decoder = opuslib_next.Decoder(16000, 1)  # 16kHz, 单声道
        pcm_data = []

        for opus_packet in opus_data:
            try:
                pcm_frame = decoder.decode(opus_packet, 960)  # 960 samples = 60ms
                pcm_data.append(pcm_frame)
            except opuslib_next.OpusError as e:
                logger.bind(tag=TAG).error(f"Opus解码错误: {e}", exc_info=True)

        with wave.open(file_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 2 bytes = 16-bit
            wf.setframerate(16000)
            wf.writeframes(b"".join(pcm_data))

        return file_path

    async def speech_to_text(
        self, opus_data: List[bytes], session_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """语音转文本主处理逻辑"""
        file_path = None
        try:
            # 保存音频文件
            start_time = time.time()
            file_path = self.save_audio_to_file(opus_data, session_id)
            logger.bind(tag=TAG).debug(
                f"音频文件保存耗时: {time.time() - start_time:.3f}s | 路径: {file_path}"
            )

            # 语音识别
            start_time = time.time()
            result = self.model.generate(
                input=file_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
            )
            text = rich_transcription_postprocess(result[0]["text"])
            logger.bind(tag=TAG).debug(
                f"语音识别耗时: {time.time() - start_time:.3f}s | 结果: {text}"
            )

            return text, file_path

        except Exception as e:
            logger.bind(tag=TAG).error(f"语音识别失败: {e}", exc_info=True)
            return "", None

        finally:
            # 文件清理逻辑
            if self.delete_audio_file and file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.bind(tag=TAG).debug(f"已删除临时音频文件: {file_path}")
                except Exception as e:
                    logger.bind(tag=TAG).error(f"文件删除失败: {file_path} | 错误: {e}")
