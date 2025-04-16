# New file: main/xiaozhi-server/core/state.py

from config.logger import setup_logging
from config.private_config import PrivateConfig
from core.utils.auth_code_gen import AuthCodeGenerator
from typing import Tuple, Optional, Dict, Any

# Initialize logger at module level
logger = setup_logging()
TAG = __name__

class StateManager:
    def __init__(self):
        # No specific initialization needed for now
        pass

    async def load_private_config(
        self,
        headers: Dict[str, str],
        config: Dict[str, Any],
        auth_code_gen: AuthCodeGenerator,
    ) -> Tuple[Optional[PrivateConfig], bool]:
        """
        Loads or creates the private configuration for a device based on headers.

        Args:
            headers: Request headers containing potentially 'device-id'.
            config: Global server configuration.
            auth_code_gen: Instance of AuthCodeGenerator.

        Returns:
            A tuple containing the PrivateConfig instance (or None if disabled/error)
            and a boolean indicating if the device is verified (has an owner).
        """
        private_config: Optional[PrivateConfig] = None
        is_device_verified = False
        device_id = headers.get("device-id")
        use_private_config_flag = config.get("use_private_config", False)

        if use_private_config_flag and device_id:
            logger.bind(tag=TAG).info(f"Attempting to load private config for device: {device_id}")
            try:
                pc = PrivateConfig(device_id, config, auth_code_gen)
                await pc.load_or_create()
                owner = pc.get_owner()
                is_device_verified = owner is not None
                private_config = pc
                logger.bind(tag=TAG).info(f"Private config loaded for device {device_id}. Verified: {is_device_verified}")
                # Note: Updating last chat time is handled separately after LLM/TTS instance update in ConnectionHandler
            except Exception as e:
                logger.bind(tag=TAG).error(
                    f"Error initializing private config for device {device_id}: {e}",
                    exc_info=True
                )
                # Return None for private_config on error
        elif not use_private_config_flag:
            logger.bind(tag=TAG).debug("Private config usage is disabled.")
        elif not device_id:
             logger.bind(tag=TAG).debug("No device-id provided in headers, cannot load private config.")


        return private_config, is_device_verified

    async def save_memory(self, memory_module: Any, dialogue_history: list):
        """
        Saves the dialogue memory using the provided memory module.

        Args:
            memory_module: The instance of the memory component (e.g., MemoryManager).
            dialogue_history: The list representing the dialogue history to save.
        """
        if not memory_module:
            logger.bind(tag=TAG).warning("Memory module is not available, skipping memory save.")
            return

        try:
            logger.bind(tag=TAG).debug("Attempting to save memory.")
            await memory_module.save_memory(dialogue_history)
            logger.bind(tag=TAG).info("Memory saved successfully.")
        except Exception as e:
            logger.bind(tag=TAG).error(f"Failed to save memory: {e}", exc_info=True)

# Placeholder load/save methods from the original plan (kept for reference, but logic moved)
#    async def load(self, connection_id: str):
#        # Placeholder - implement actual loading logic
#        print(f"Placeholder: Loading state for {connection_id}")
#        return {}

#    async def save(self, connection_id: str, state_data: dict):
#        # Placeholder - implement actual saving logic
#        print(f"Placeholder: Saving state for {connection_id}")
#        pass 