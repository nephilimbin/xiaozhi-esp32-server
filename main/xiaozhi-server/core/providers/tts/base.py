import asyncio
from config.logger import setup_logging
import os
import numpy as np
import opuslib_next
from pydub import AudioSegment
from abc import ABC, abstractmethod
from core.utils.tts import MarkdownCleaner
import random
import time

TAG = __name__
logger = setup_logging()


class TTSProviderBase(ABC):
    def __init__(self, config, delete_audio_file):
        self.delete_audio_file = delete_audio_file
        self.output_file = config.get("output_dir")

    @abstractmethod
    def generate_filename(self):
        pass

    def to_tts(self, text):
        tmp_file = self.generate_filename()
        try:
            max_repeat_time = 5
            text = MarkdownCleaner.clean_markdown(text)
            attempts = 0
            while not os.path.exists(tmp_file) and attempts < max_repeat_time:
                attempts += 1
                sleep_time = random.uniform(0.1, 0.2)
                logger.bind(tag=TAG).debug(f"等待 {sleep_time:.2f} 秒后尝试生成 TTS...")
                time.sleep(sleep_time)

                asyncio.run(self.text_to_speak(text, tmp_file))
                if not os.path.exists(tmp_file):
                    logger.bind(tag=TAG).error(f"语音生成失败: {text}:{tmp_file}，剩余尝试次数 {max_repeat_time - attempts}")
                else:
                    break

            if os.path.exists(tmp_file):
                logger.bind(tag=TAG).info(f"语音生成成功: {text}:{tmp_file}，尝试 {attempts} 次")
                return tmp_file
            else:
                logger.bind(tag=TAG).error(f"语音生成失败，已达到最大重试次数: {text}:{tmp_file}")
                return None

        except Exception as e:
            logger.bind(tag=TAG).error(f"生成 TTS 文件时发生异常: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError as oe:
                    logger.bind(tag=TAG).error(f"删除异常 TTS 文件 {tmp_file} 失败: {oe}")
            return None

    @abstractmethod
    async def text_to_speak(self, text, output_file):
        pass

    def audio_to_opus_data(self, audio_file_path):
        """音频文件转换为Opus编码"""
        # 获取文件后缀名
        file_type = os.path.splitext(audio_file_path)[1]
        if file_type:
            file_type = file_type.lstrip('.')
        # 读取音频文件，-nostdin 参数：不要从标准输入读取数据，否则FFmpeg会阻塞
        audio = AudioSegment.from_file(audio_file_path, format=file_type, parameters=["-nostdin"])

        # 转换为单声道/16kHz采样率/16位小端编码（确保与编码器匹配）
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)

        # 音频时长(秒)
        duration = len(audio) / 1000.0

        # 获取原始PCM数据（16位小端）
        raw_data = audio.raw_data

        # 初始化Opus编码器
        encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)

        # 编码参数
        frame_duration = 60  # 60ms per frame
        frame_size = int(16000 * frame_duration / 1000)  # 960 samples/frame

        opus_datas = []
        # 按帧处理所有音频数据（包括最后一帧可能补零）
        for i in range(0, len(raw_data), frame_size * 2):  # 16bit=2bytes/sample
            # 获取当前帧的二进制数据
            chunk = raw_data[i:i + frame_size * 2]

            # 如果最后一帧不足，补零
            if len(chunk) < frame_size * 2:
                chunk += b'\x00' * (frame_size * 2 - len(chunk))

            # 转换为numpy数组处理
            np_frame = np.frombuffer(chunk, dtype=np.int16)

            # 编码Opus数据
            opus_data = encoder.encode(np_frame.tobytes(), frame_size)
            opus_datas.append(opus_data)

        return opus_datas, duration
