"""
Custom nodes for testing ComfyUI-to-Python-Extension
"""
import asyncio
import os
import tempfile
from typing import Dict, Any, Tuple


class LoadTextSync:
    """
    Synchronous text loading node for testing
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "Hello World"}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "load_text"
    CATEGORY = "testing/text"
    
    def load_text(self, text: str) -> Tuple[str]:
        """Load and return text"""
        return (text,)


class SaveTextSync:
    """
    Synchronous text saving node for testing
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "test_output"}),
            }
        }
    
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_text"
    CATEGORY = "testing/text"
    
    def save_text(self, text: str, filename_prefix: str = "test_output") -> Dict[str, Any]:
        """Save text to a file"""
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', 
            delete=False, 
            prefix=filename_prefix + "_",
            suffix=".txt"
        )
        
        with temp_file:
            temp_file.write(text)
        
        return {
            "result": (text,),
            "ui": {"text": [text]},
            "filename": temp_file.name
        }


class LoadTextAsync:
    """
    Asynchronous text loading node for testing
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "Hello Async World"}),
                "delay": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 5.0}),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    FUNCTION = "load_text_async"
    CATEGORY = "testing/text"
    
    async def load_text_async(self, text: str, delay: float = 0.1) -> Tuple[str]:
        """Load text asynchronously with optional delay"""
        await asyncio.sleep(delay)
        return (text,)


class SaveTextAsync:
    """
    Asynchronous text saving node for testing
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "test_async_output"}),
                "delay": ("FLOAT", {"default": 0.1, "min": 0.0, "max": 5.0}),
            }
        }
    
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_text_async"
    CATEGORY = "testing/text"
    
    async def save_text_async(self, text: str, filename_prefix: str = "test_async_output", delay: float = 0.1) -> Dict[str, Any]:
        """Save text to a file asynchronously"""
        await asyncio.sleep(delay)
        
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', 
            delete=False, 
            prefix=filename_prefix + "_",
            suffix=".txt"
        )
        
        with temp_file:
            temp_file.write(text)
        
        return {
            "result": (text,),
            "ui": {"text": [text]},
            "filename": temp_file.name
        }


# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "LoadTextSync": LoadTextSync,
    "SaveTextSync": SaveTextSync,
    "LoadTextAsync": LoadTextAsync,
    "SaveTextAsync": SaveTextAsync,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadTextSync": "Load Text (Sync)",
    "SaveTextSync": "Save Text (Sync)",
    "LoadTextAsync": "Load Text (Async)",
    "SaveTextAsync": "Save Text (Async)",
}
