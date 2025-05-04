# -*- encoding: utf-8 -*-
import os
# --- Start: Add project root to sys.path ---
# import sys # Comment out sys.path modification
# import pathlib
#
# # Get the absolute path of the current script
# script_path = pathlib.Path(__file__).resolve()
# # Get the directory containing the script (asr)
# script_dir = script_path.parent
# # Get the path to the project root (main/xiaozhi-server) by going up two levels
# project_root = script_dir.parent.parent.parent
# # Add the project root to sys.path
# sys.path.insert(0, str(project_root))
# --- End: Add project root to sys.path ---

import websockets
import ssl
import asyncio
import json
# import logging # Use standard logging <-- Remove standard logging
from typing import Optional, Tuple, List, Dict, Any
import wave # <-- Remove comment
import time
from urllib.parse import urlparse # <-- Add urlparse
import opuslib_next # <-- Add opuslib
import uuid # <-- Add uuid

from .base import ASRProviderBase # <-- Restore base class import
from config.logger import setup_logging # <-- Restore project logger import

TAG = "FunasrDockerASRProvider"
logger = setup_logging() # <-- Use project logger


# class ASRProvider(): # Keep base class commented out
class ASRProvider(ASRProviderBase):
    """
    ASRProvider implementation using FunASR Docker via WebSocket.
    Connects to a running FunASR WebSocket server to perform speech-to-text.
    Processes Opus audio data.
    """

    def __init__(self, config: Dict[str, Any], delete_audio_file: bool = False): # delete_audio_file might be unused here
        """
        Initializes the FunASR Docker ASR provider.

        Args:
            config (Dict[str, Any]): Configuration dictionary containing:
                - base_url (str): Full WebSocket URL (e.g., "wss://127.0.0.1:10095").
                - output_dir (str, optional): Directory path (currently unused).
                - hotword (str, optional): Hotword file path or string. Defaults to "".
                # Other potential configs can be added later if needed
            delete_audio_file (bool): Currently unused by this provider.
        """
        base_url = config.get("base_url")
        self.output_dir_config = config.get("output_dir", "tmp/") # Store but might not use
        if not base_url:
            raise ValueError("Missing 'base_url' in ASRProvider config for FunASR_Docker")

        parsed_url = urlparse(base_url)
        self.ssl_enabled = parsed_url.scheme == "wss"
        self.host = parsed_url.hostname
        self.port = parsed_url.port

        if not self.host or not self.port:
             raise ValueError(f"Could not parse host/port from base_url: {base_url}")

        # Keep other parameters as defaults for now
        self.mode = config.get("mode", "2pass")  # Example: allow override later if needed
        self.chunk_size = config.get("chunk_size", [5, 10, 5])
        self.chunk_interval = config.get("chunk_interval", 10)
        self.encoder_chunk_look_back = config.get("encoder_chunk_look_back", 4)
        self.decoder_chunk_look_back = config.get("decoder_chunk_look_back", 0)
        self.hotword = config.get("hotword", "") # Allow hotword config
        self.use_itn = config.get("use_itn", True)

        # self.delete_audio_file = delete_audio_file # Store if needed later

        self.uri = base_url # Use the full base_url as the URI
        self.ssl_context = self._build_ssl_context()
        self.hotword_msg = self._prepare_hotword_msg()

        logger.bind(tag=TAG).info(f"Initialized FunASR Docker ASR provider connecting to {self.uri}")

    def _build_uri(self) -> str:
        """Builds the WebSocket URI."""
        # Now redundant as we take base_url directly
        # protocol = "wss" if self.ssl_enabled else "ws"
        # return f"{protocol}://{self.host}:{self.port}"
        return self.uri

    def _build_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Builds the SSL context if SSL is enabled."""
        if self.ssl_enabled:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            # FunASR Docker often uses self-signed certs, allow them for ease of use.
            # For production, proper cert validation is recommended.
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            return ssl_context
        return None

    def _prepare_hotword_msg(self) -> str:
        """Prepares the hotword message string."""
        hotword_msg = ""
        if self.hotword and self.hotword.strip() != "":
            if os.path.exists(self.hotword):
                try:
                    fst_dict = {}
                    with open(self.hotword, 'r', encoding='utf-8') as f_scp:
                        hot_lines = f_scp.readlines()
                        for line in hot_lines:
                            words = line.strip().split(" ")
                            if len(words) < 2:
                                logger.bind(tag=TAG).warning(f"Skipping invalid hotword line: {line.strip()}")
                                continue
                            try:
                                fst_dict[" ".join(words[:-1])] = int(words[-1])
                            except ValueError:
                                logger.bind(tag=TAG).warning(f"Skipping invalid hotword line (format error): {line.strip()}")
                        hotword_msg = json.dumps(fst_dict)
                except Exception as e:
                    logger.bind(tag=TAG).error(f"Error reading hotword file {self.hotword}: {e}", exc_info=True)
                    hotword_msg = "" # Fallback to empty if error
            else:
                # Treat as direct hotword string if not a file path
                # Example: "阿里巴巴 20" - needs proper JSON formatting by user if complex
                hotword_msg = self.hotword
        return hotword_msg

    def save_audio_to_file(self, opus_data: List[bytes], session_id: str) -> str:
        """将Opus音频数据解码并保存为WAV文件"""
        file_name = f"asr_{session_id}_{uuid.uuid4()}.wav"
        # Use the configured output directory
        os.makedirs(self.output_dir_config, exist_ok=True)
        file_path = os.path.join(self.output_dir_config, file_name)

        try:
            decoder = opuslib_next.Decoder(16000, 1)  # 16kHz, 单声道
            pcm_data = []
            for opus_packet in opus_data:
                    pcm_frame = decoder.decode(opus_packet, 960)  # 960 samples = 60ms
                    pcm_data.append(pcm_frame)

            with wave.open(file_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 2 bytes = 16-bit
                wf.setframerate(16000)
                wf.writeframes(b"".join(pcm_data))
            logger.bind(tag=TAG, session=session_id).debug(f"Opus data saved to WAV file: {file_path}")
            return file_path
        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG, session=session_id).error(f"Opus decoding error during save: {e}", exc_info=True)
            raise # Re-raise exception as saving failed
        except Exception as e:
            logger.bind(tag=TAG, session=session_id).error(f"Failed to save Opus data to WAV: {e}", exc_info=True)
            raise # Re-raise exception

    async def speech_to_text(self, opus_data: List[bytes], session_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Performs speech-to-text on the given Opus audio data using FunASR Docker.

        Args:
            opus_data (List[bytes]): List of Opus audio packets.
            session_id (str): Identifier for the current session (used for logging).

        Returns:
            Tuple[Optional[str], Optional[str]]: A tuple containing:
                - The recognized text (str) or None if an error occurred.
                - None (as file path is not applicable here).
        """
        websocket: Optional[websockets.WebSocketClientProtocol] = None
        result_text: Optional[str] = None
        final_result_received = asyncio.Event()
        accumulated_text = ""

        # --- Decode Opus to PCM --- Start ---
        pcm_data = []
        try:
            decoder = opuslib_next.Decoder(16000, 1) # 16kHz, 1 channel
            logger.bind(tag=TAG, session=session_id).debug("Decoding Opus packets to PCM...")
            total_opus_bytes = 0
            for opus_packet in opus_data:
                total_opus_bytes += len(opus_packet)
                pcm_frame = decoder.decode(opus_packet, 960) # frame_size=960 for 60ms at 16kHz
                pcm_data.append(pcm_frame)
            audio_data = b"".join(pcm_data)
            logger.bind(tag=TAG, session=session_id).debug(f"Decoded {total_opus_bytes} Opus bytes to {len(audio_data)} PCM bytes.")
        except opuslib_next.OpusError as e:
            logger.bind(tag=TAG, session=session_id).error(f"Opus decoding failed: {e}", exc_info=True)
            return None, None # Cannot proceed without PCM data
        except Exception as e:
             logger.bind(tag=TAG, session=session_id).error(f"An unexpected error occurred during Opus decoding: {e}", exc_info=True)
             return None, None
        # --- Decode Opus to PCM --- End ---

        if not audio_data:
             logger.bind(tag=TAG, session=session_id).warning("Opus decoding resulted in empty PCM data.")
             return None, None

        try:
            logger.bind(tag=TAG, session=session_id).debug(f"Connecting to FunASR Docker at {self.uri}")
            async with websockets.connect(
                self.uri,
                subprotocols=["binary"],
                ping_interval=None,
                ssl=self.ssl_context
            ) as websocket:
                logger.bind(tag=TAG, session=session_id).info("WebSocket connection established.")

                # 1. Send configuration message
                config_message = json.dumps({
                    "mode": self.mode,
                    "chunk_size": self.chunk_size,
                    "chunk_interval": self.chunk_interval,
                    "encoder_chunk_look_back": self.encoder_chunk_look_back,
                    "decoder_chunk_look_back": self.decoder_chunk_look_back,
                    "audio_fs": 16000, # We send 16kHz PCM
                    "wav_name": f"session_{session_id}",
                    "wav_format": "pcm", # We send PCM
                    "is_speaking": True,
                    "hotwords": self.hotword_msg,
                    "itn": self.use_itn,
                })
                logger.bind(tag=TAG, session=session_id).debug(f"Sending config: {config_message}")
                await websocket.send(config_message)

                # 2. Start receiving messages in a separate task
                async def receive_messages():
                    nonlocal result_text, accumulated_text, final_result_received
                    try:
                        while True:
                            message = await websocket.recv()
                            logger.bind(tag=TAG, session=session_id).debug(f"Received message: {message}")
                            try:
                                meg = json.loads(message)
                                text = meg.get("text", "")
                                mode = meg.get("mode", "")
                                is_final = meg.get("is_final", False)

                                if mode == "online":
                                    accumulated_text += text
                                elif mode == "offline":
                                    accumulated_text = text
                                    final_result_received.set()
                                elif mode == "2pass-online":
                                    accumulated_text += text
                                elif mode == "2pass-offline":
                                    accumulated_text = text
                                    final_result_received.set()
                                else:
                                    accumulated_text += text

                                logger.bind(tag=TAG, session=session_id).info(f"Partial/Final Result ({mode}): {text}")

                                if is_final or mode in ["offline", "2pass-offline"]:
                                     final_result_received.set()
                                     break

                            except json.JSONDecodeError:
                                logger.bind(tag=TAG, session=session_id).warning(f"Received non-JSON message: {message}")
                            except Exception as e:
                                logger.bind(tag=TAG, session=session_id).error(f"Error processing message: {e}", exc_info=True)
                                final_result_received.set()
                                break
                    except websockets.exceptions.ConnectionClosedOK:
                        logger.bind(tag=TAG, session=session_id).info("WebSocket connection closed normally by server.")
                        final_result_received.set()
                    except websockets.exceptions.ConnectionClosedError as e:
                        logger.bind(tag=TAG, session=session_id).error(f"WebSocket connection closed with error: {e}", exc_info=True)
                        final_result_received.set()
                    except Exception as e:
                        logger.bind(tag=TAG, session=session_id).error(f"Error in receive loop: {e}", exc_info=True)
                        final_result_received.set()

                receive_task = asyncio.create_task(receive_messages())

                # 3. Send audio data in chunks
                stride_ms = 60 * self.chunk_size[1] / self.chunk_interval
                stride = int(stride_ms * 16 * 2) # 16kHz, 16-bit (2 bytes)
                logger.bind(tag=TAG, session=session_id).debug(f"Audio chunk stride: {stride} bytes ({stride_ms} ms)")

                total_bytes = len(audio_data)
                bytes_sent = 0
                start_time = time.time()

                while bytes_sent < total_bytes:
                    chunk = audio_data[bytes_sent : bytes_sent + stride]
                    if not chunk:
                        break
                    await websocket.send(chunk)
                    bytes_sent += len(chunk)
                    logger.bind(tag=TAG, session=session_id).debug(f"Sent audio chunk: {len(chunk)} bytes / Total sent: {bytes_sent}")
                    # await asyncio.sleep(stride_ms / 1000.0 * 0.8) <-- Original sleep
                    # --- Conditional sleep based on mode --- Start ---
                    # if self.mode == "offline":
                    #     await asyncio.sleep(0.001) # Minimal sleep for offline mode, similar to original script
                    # else:
                        # Simulate real-time for online/2pass modes
                        # await asyncio.sleep(stride_ms / 1000.0 * 0.8)
                    # --- Conditional sleep based on mode --- End ---

                end_time = time.time()
                logger.bind(tag=TAG, session=session_id).info(f"Finished sending {bytes_sent} bytes of audio data in {end_time - start_time:.2f} seconds.")

                # 4. Send end-of-speech signal
                eos_message = json.dumps({"is_speaking": False})
                logger.bind(tag=TAG, session=session_id).debug(f"Sending end-of-speech signal: {eos_message}")
                await websocket.send(eos_message)

                # 5. Wait for the final result from the receiving task
                logger.bind(tag=TAG, session=session_id).info("Waiting for final recognition result...")
                try:
                     await asyncio.wait_for(final_result_received.wait(), timeout=30.0)
                     result_text = accumulated_text
                     logger.bind(tag=TAG, session=session_id).info(f"Final result received: {result_text}")
                except asyncio.TimeoutError:
                     logger.bind(tag=TAG, session=session_id).error("Timeout waiting for final result from server.")
                     result_text = accumulated_text

                # 6. Ensure receiver task is cleaned up
                receive_task.cancel()
                try:
                    await receive_task
                except asyncio.CancelledError:
                    logger.bind(tag=TAG, session=session_id).debug("Receive task cancelled successfully.")

        except websockets.exceptions.InvalidURI as e:
            logger.bind(tag=TAG, session=session_id).error(f"Invalid WebSocket URI: {self.uri} - {e}", exc_info=True)
            result_text = None
        except websockets.exceptions.ConnectionClosedError as e:
             logger.bind(tag=TAG, session=session_id).error(f"Connection closed unexpectedly: {e}", exc_info=True)
             result_text = accumulated_text if accumulated_text else None # Return partial if available
        except ConnectionRefusedError:
            logger.bind(tag=TAG, session=session_id).error(f"Connection refused by server at {self.uri}. Is the FunASR Docker server running and accessible?")
            result_text = None
        except Exception as e:
            logger.bind(tag=TAG, session=session_id).error(f"An error occurred during ASR: {e}", exc_info=True)
            result_text = None # Or return partial: accumulated_text
        finally:
            # The `async with websockets.connect(...)` block handles closing the connection
            # automatically upon exiting the block (normally or due to an exception inside it).
            # Therefore, explicitly closing it again in this outer finally block is usually
            # unnecessary and can sometimes cause issues if the connection state is unexpected.
            # We keep the finally block in case we need other cleanup later, but remove the ws close logic.
            # if websocket and websocket.open: # <-- Incorrect check: use .open attribute
            #     await websocket.close()
            #     # logger.bind(tag=TAG, session=session_id).info("WebSocket connection closed.")
            #     logging.info(f"[{session_id}] WebSocket connection closed.")
            pass # No explicit websocket closing needed here due to async with

        # Return the final text and None for file path
        return result_text, None
