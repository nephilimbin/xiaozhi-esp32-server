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
            text = MarkdownCleaner.clean_markdown(text)
            logger.bind(tag=TAG).debug(f"Attempting to generate TTS to {tmp_file} for text: '{text}'")
            
            # Directly call text_to_speak once. Retries are handled by the caller.
            asyncio.run(self.text_to_speak(text, tmp_file))

            # Check if file exists after the call
            if os.path.exists(tmp_file):
                # Optional: Check file size > 0 if empty files are possible on success
                if os.path.getsize(tmp_file) > 0:
                    logger.bind(tag=TAG).info(f"TTS generation successful: {tmp_file}")
                    return tmp_file
                else:
                    logger.bind(tag=TAG).error(f"TTS generated an empty file: {tmp_file} for text: '{text}'")
                    # Attempt to remove the empty file
                    try:
                        os.remove(tmp_file)
                    except OSError as oe:
                        logger.bind(tag=TAG).error(f"Failed to remove empty TTS file {tmp_file}: {oe}")
                    return None # Treat empty file as failure
            else:
                logger.bind(tag=TAG).error(f"TTS file not found after generation attempt: {tmp_file} for text: '{text}'")
                return None

        except Exception as e:
            # Log the exception originating from text_to_speak (e.g., network timeout)
            logger.bind(tag=TAG).error(f"Exception during TTS generation for {tmp_file}: {e}", exc_info=True)
            # Attempt to clean up the possibly partially created file
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError as oe:
                    logger.bind(tag=TAG).error(f"Failed to remove failed TTS file {tmp_file}: {oe}")
            return None # Signal failure to the caller

    @abstractmethod
    async def text_to_speak(self, text, output_file):
        pass

    def audio_to_opus_data(self, audio_file_path):
        """音频文件转换为Opus编码"""
        # 获取文件后缀名
        file_type = os.path.splitext(audio_file_path)[1]
        if file_type:
            file_type = file_type.lstrip('.')
        
        try:
             # 读取音频文件，-nostdin 参数：不要从标准输入读取数据，否则FFmpeg会阻塞
            audio = AudioSegment.from_file(audio_file_path, format=file_type, parameters=["-nostdin"])
        except FileNotFoundError:
            logger.bind(tag=TAG).error(f"Audio file not found for Opus conversion: {audio_file_path}")
            return [], 0.0
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error reading audio file {audio_file_path}: {e}", exc_info=True)
            return [], 0.0

        # 转换为单声道/16kHz采样率/16位小端编码（确保与编码器匹配）
        try:
            audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        except Exception as e:
            logger.bind(tag=TAG).error(f"Error processing audio segment for {audio_file_path}: {e}", exc_info=True)
            return [], 0.0

        # 音频时长(秒)
        duration = len(audio) / 1000.0

        # 获取原始PCM数据（16位小端）
        raw_data = audio.raw_data

        opus_datas = []
        try:
            # 初始化Opus编码器
            encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)

            # 编码参数
            frame_duration = 60  # 60ms per frame
            frame_size = int(16000 * frame_duration / 1000)  # 960 samples/frame

            
            # 按帧处理所有音频数据（包括最后一帧可能补零）
            for i in range(0, len(raw_data), frame_size * 2):  # 16bit=2bytes/sample
                # 获取当前帧的二进制数据
                chunk = raw_data[i:i + frame_size * 2]

                # 如果最后一帧不足，补零
                if len(chunk) < frame_size * 2:
                    chunk += b'\x00' * (frame_size * 2 - len(chunk))

                # 转换为numpy数组处理 - Numba might optimize this if needed later
                # np_frame = np.frombuffer(chunk, dtype=np.int16)
                # 直接使用 bytes

                # 编码Opus数据
                # opus_data = encoder.encode(np_frame.tobytes(), frame_size)
                opus_data = encoder.encode(chunk, frame_size)
                opus_datas.append(opus_data)
        except Exception as e:
             logger.bind(tag=TAG).error(f"Error during Opus encoding for {audio_file_path}: {e}", exc_info=True)
             return [], 0.0 # Return empty list on encoding error

        return opus_datas, duration
