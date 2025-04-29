# -*- encoding: utf-8 -*-
import os
import websockets
import ssl
import asyncio
import json
import logging
from typing import Optional, Tuple, List, Dict, Any
import wave
import time
# from core.providers.asr.base import ASRProviderBase
from config.logger import setup_logging

TAG = "FunasrDockerASRProvider"
logger = setup_logging()


class ASRProvider():
    """
    ASRProvider implementation using FunASR Docker via WebSocket.
    Connects to a running FunASR WebSocket server to perform speech-to-text.
    """

    def __init__(self, config: Dict[str, Any], delete_audio_file: bool = False):
        """
        Initializes the FunASR Docker ASR provider.

        Args:
            config (Dict[str, Any]): Configuration dictionary containing parameters like:
                - host (str): Host IP of the FunASR WebSocket server.
                - port (int): Port of the FunASR WebSocket server.
                - mode (str): ASR mode ("offline", "online", "2pass"). Defaults to "2pass".
                - chunk_size (List[int]): Chunk sizes. Defaults to [5, 10, 5].
                - chunk_interval (int): Chunk interval. Defaults to 10.
                - encoder_chunk_look_back (int): Encoder chunk look back. Defaults to 4.
                - decoder_chunk_look_back (int): Decoder chunk look back. Defaults to 0.
                - hotword (str): Hotword file path or string. Defaults to "".
                - use_itn (bool): Whether to use Inverse Text Normalization. Defaults to True.
                - ssl (bool): Whether to use SSL for connection. Defaults to True.
                - output_dir (str, optional): Directory to save temporary audio files if needed.
            delete_audio_file (bool): Whether to delete temporary audio files (if created).
                                      Note: This implementation sends bytes directly,
                                      so file saving/deletion might not be primary.
        """
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 10095)
        self.mode = config.get("mode", "2pass")  # offline, online, 2pass
        self.chunk_size = config.get("chunk_size", [5, 10, 5])
        self.chunk_interval = config.get("chunk_interval", 10)
        self.encoder_chunk_look_back = config.get("encoder_chunk_look_back", 4)
        self.decoder_chunk_look_back = config.get("decoder_chunk_look_back", 0)
        self.hotword = config.get("hotword", "")
        self.use_itn = config.get("use_itn", True)
        self.ssl_enabled = config.get("ssl", True)
        # self.output_dir = config.get("output_dir") # Not strictly needed if sending bytes
        # self.delete_audio_file = delete_audio_file # Not strictly needed

        self.uri = self._build_uri()
        self.ssl_context = self._build_ssl_context()
        self.hotword_msg = self._prepare_hotword_msg()

        logger.bind(tag=TAG).info(f"Initialized FunASR Docker ASR provider connecting to {self.uri}")

    def _build_uri(self) -> str:
        """Builds the WebSocket URI."""
        protocol = "wss" if self.ssl_enabled else "ws"
        return f"{protocol}://{self.host}:{self.port}"

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

    async def speech_to_text(self, audio_data: bytes, session_id: str, wav_name: str = "session_audio") -> Tuple[Optional[str], Optional[str]]:
        """
        Performs speech-to-text on the given audio data using FunASR Docker.

        Args:
            audio_data (bytes): Raw PCM audio data (16kHz, 16-bit mono).
            session_id (str): Identifier for the current session (used for logging).
            wav_name (str): Name to associate with the audio segment (sent to server).

        Returns:
            Tuple[Optional[str], Optional[str]]: A tuple containing:
                - The recognized text (str) or None if an error occurred.
                - None (as file path is not applicable here).
        """
        websocket: Optional[websockets.WebSocketClientProtocol] = None
        result_text: Optional[str] = None
        final_result_received = asyncio.Event()
        accumulated_text = ""

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
                    "audio_fs": 16000, # Assuming 16kHz PCM input
                    "wav_name": wav_name,
                    "wav_format": "pcm", # Sending raw PCM bytes
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
                                is_final = meg.get("is_final", False) # Check for explicit final flag if server sends one

                                # Accumulate text based on mode
                                if mode == "online":
                                    # Append only the new part if possible, otherwise replace
                                    # (Simple accumulation for now)
                                    accumulated_text += text # May need smarter handling based on server behavior
                                elif mode == "offline":
                                    accumulated_text = text # Offline usually sends full result
                                    final_result_received.set() # Signal final result for offline
                                elif mode == "2pass-online":
                                    # Handle 2pass online updates (might need adjustment)
                                    accumulated_text += text # Simple accumulation
                                elif mode == "2pass-offline":
                                    # Handle 2pass offline final result
                                    accumulated_text = text # Assume final result replaces previous
                                    final_result_received.set() # Signal final result
                                else:
                                     # Fallback for unknown modes or messages without mode
                                    accumulated_text += text

                                logger.bind(tag=TAG, session=session_id).info(f"Partial/Final Result ({mode}): {text}")

                                # If server explicitly marks finality or mode suggests it
                                if is_final or mode in ["offline", "2pass-offline"]:
                                     final_result_received.set()
                                     break # Stop listening once final result is confirmed


                            except json.JSONDecodeError:
                                logger.bind(tag=TAG, session=session_id).warning(f"Received non-JSON message: {message}")
                            except Exception as e:
                                logger.bind(tag=TAG, session=session_id).error(f"Error processing message: {e}", exc_info=True)
                                final_result_received.set() # Signal error to stop waiting
                                break
                    except websockets.exceptions.ConnectionClosedOK:
                        logger.bind(tag=TAG, session=session_id).info("WebSocket connection closed normally by server.")
                        final_result_received.set() # Ensure waiting task unblocks
                    except websockets.exceptions.ConnectionClosedError as e:
                        logger.bind(tag=TAG, session=session_id).error(f"WebSocket connection closed with error: {e}", exc_info=True)
                        final_result_received.set() # Ensure waiting task unblocks
                    except Exception as e:
                        logger.bind(tag=TAG, session=session_id).error(f"Error in receive loop: {e}", exc_info=True)
                        final_result_received.set() # Ensure waiting task unblocks


                receive_task = asyncio.create_task(receive_messages())

                # 3. Send audio data in chunks
                # Calculate stride based on chunk_size[1] and chunk_interval
                # chunk_size[1] = 10ms block size? chunk_interval = 10? -> 60 * 10 / 10 = 60ms?
                # Let's assume chunk_size[1] is the duration in ms for the processing chunk
                # Let chunk_interval be the sending interval multiplier
                # Sample Rate = 16000 Hz (16 samples per ms)
                # Bytes per sample = 2 (16-bit)
                # Stride in ms = 60 * chunk_size[1] / chunk_interval
                # Stride in bytes = Stride in ms * 16 samples/ms * 2 bytes/sample
                stride_ms = 60 * self.chunk_size[1] / self.chunk_interval
                stride = int(stride_ms * 16 * 2)
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

                    # Simulate sleep based on audio duration sent, adjust if needed
                    await asyncio.sleep(stride_ms / 1000.0 * 0.8) # Sleep slightly less than chunk duration

                end_time = time.time()
                logger.bind(tag=TAG, session=session_id).info(f"Finished sending {bytes_sent} bytes of audio data in {end_time - start_time:.2f} seconds.")

                # 4. Send end-of-speech signal
                eos_message = json.dumps({"is_speaking": False})
                logger.bind(tag=TAG, session=session_id).debug(f"Sending end-of-speech signal: {eos_message}")
                await websocket.send(eos_message)

                # 5. Wait for the final result from the receiving task
                logger.bind(tag=TAG, session=session_id).info("Waiting for final recognition result...")
                try:
                     await asyncio.wait_for(final_result_received.wait(), timeout=30.0) # Add timeout
                     result_text = accumulated_text # Use the text accumulated by the receiver task
                     logger.bind(tag=TAG, session=session_id).info(f"Final result received: {result_text}")
                except asyncio.TimeoutError:
                     logger.bind(tag=TAG, session=session_id).error("Timeout waiting for final result from server.")
                     result_text = accumulated_text # Return whatever was accumulated

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
            if websocket and not websocket.closed:
                await websocket.close()
                logger.bind(tag=TAG, session=session_id).info("WebSocket connection closed.")

        # Return the final text and None for file path
        return result_text, None

# --- Test Main Block ---
async def main_test():
    """Main function for testing the ASRProvider."""
    # --- Configuration ---
    # IMPORTANT: Replace with your actual FunASR Docker server details and audio file path
    test_config = {
        "host": "127.0.0.1",  # IP address where FunASR Docker WS is running
        "port": 10095,        # Port number
        "ssl": False,         # Set to True if your server uses wss://
        "mode": "offline",      # Or "offline", "online"
        "hotword": ""         # Optional: path to hotword file or hotword string
        # Add other parameters if needed (chunk_size, etc.)
    }
    # Path to a test WAV file (must be 16kHz, 16-bit mono PCM for this example)
    # You might need to convert your audio file first
    test_audio_path = "../../../tmp/1.mp3" #<---- IMPORTANT: REPLACE WITH YOUR FILE

    if not os.path.exists(test_audio_path):
         print(f"Error: Test audio file not found at '{test_audio_path}'")
         print(f"Please replace '{test_audio_path}' with the path to a valid 16kHz, 16-bit mono WAV file.")
         return

    # --- Initialization ---
    provider = ASRProvider(config=test_config)

    # --- Read Audio Data ---
    try:
        with wave.open(test_audio_path, 'rb') as wf:
            # Verify audio format (optional but recommended)
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
                print(f"Error: Audio file '{test_audio_path}' is not 16kHz, 16-bit mono PCM.")
                return
            audio_bytes = wf.readframes(wf.getnframes())
            print(f"Read {len(audio_bytes)} bytes from {test_audio_path}")
    except wave.Error as e:
        print(f"Error reading WAV file: {e}")
        return
    except Exception as e:
        print(f"An unexpected error occurred reading the audio file: {e}")
        return


    # --- Perform ASR ---
    session_id = "test_session_001"
    print(f"\nPerforming ASR for session: {session_id}...")
    start_asr_time = time.time()
    text_result, _ = await provider.speech_to_text(audio_bytes, session_id=session_id, wav_name=os.path.basename(test_audio_path))
    end_asr_time = time.time()


    # --- Print Result ---
    if text_result is not None:
        print(f"\nASR Result: {text_result}")
    else:
        print("\nASR failed.")

    print(f"ASR processing time: {end_asr_time - start_asr_time:.2f} seconds")


if __name__ == "__main__":
    print("Running FunASR Docker ASR Provider Test...")
    # Setup basic logging for the test
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    asyncio.run(main_test())
