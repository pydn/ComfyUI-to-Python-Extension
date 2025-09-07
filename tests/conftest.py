"""
Pytest configuration and fixtures for ComfyUI-to-Python-Extension tests
"""
import os
import sys
import tempfile
import shutil
import pytest
from pathlib import Path
from typing import Optional


def find_comfyui_installation() -> Optional[str]:
    """
    Auto-discover local ComfyUI installation by searching common locations
    """
    search_paths = [
        # Current working directory and parent directories
        os.getcwd(),
        os.path.dirname(os.getcwd()),
        os.path.dirname(os.path.dirname(os.getcwd())),
        
        # Common installation locations
        os.path.expanduser("~/ComfyUI"),
        os.path.expanduser("~/Desktop/ComfyUI"),
        os.path.expanduser("~/Documents/ComfyUI"),
        "/opt/ComfyUI",
        "/usr/local/ComfyUI",
        
        # Development locations
        os.path.expanduser("~/src/ComfyUI"),
        os.path.expanduser("~/github/ComfyUI"),
        os.path.expanduser("~/git/ComfyUI"),
        os.path.expanduser("~/dev/ComfyUI"),
        os.path.expanduser("~/projects/ComfyUI"),
    ]
    
    for path in search_paths:
        if os.path.isdir(path):
            # Check if this looks like a ComfyUI installation
            comfyui_indicators = [
                "main.py",
                "nodes.py", 
                "execution.py",
                "custom_nodes",
                "models"
            ]
            
            if all(os.path.exists(os.path.join(path, indicator)) 
                   for indicator in comfyui_indicators[:3]):  # Check for main files
                print(f"Found ComfyUI installation at: {path}")
                return path
    
    # Also check if ComfyUI is already in sys.path
    for path in sys.path:
        if path.endswith("ComfyUI") and os.path.isdir(path):
            if os.path.exists(os.path.join(path, "main.py")):
                print(f"Found ComfyUI in sys.path: {path}")
                return path
    
    return None


@pytest.fixture(scope="session")
def comfyui_path():
    """
    Find and return the path to a local ComfyUI installation
    """
    path = find_comfyui_installation()
    if not path:
        pytest.skip("ComfyUI installation not found. Please ensure ComfyUI is installed locally.")
    return path


@pytest.fixture(scope="session")
def comfyui_setup(comfyui_path):
    """
    Set up ComfyUI environment for testing
    """
    # Add ComfyUI to sys.path if not already there
    if comfyui_path not in sys.path:
        sys.path.insert(0, comfyui_path)
    
    # Handle protocol module conflicts
    original_path = sys.path.copy()
    try:
        # Remove conflicting protocol packages temporarily
        modules_to_remove = []
        for module_name in list(sys.modules.keys()):
            if module_name.startswith('protocol'):
                modules_to_remove.append(module_name)
        
        for module_name in modules_to_remove:
            if module_name in sys.modules:
                del sys.modules[module_name]
        
        # Try to import ComfyUI modules
        import nodes
        print("ComfyUI modules successfully imported")
        return comfyui_path
    except ImportError as e:
        print(f"Warning: Failed to import ComfyUI modules: {e}")
        # Don't skip, just log the warning and continue
        return comfyui_path
    except Exception as e:
        print(f"Warning: Unexpected error during ComfyUI setup: {e}")
        return comfyui_path


@pytest.fixture
def temp_dir():
    """
    Create a temporary directory for test files
    """
    temp_path = tempfile.mkdtemp()
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def test_image_path():
    """
    Create a simple test image for LoadImage tests
    """
    try:
        from PIL import Image
        import numpy as np
        
        # Create a simple test image
        image_array = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
        image = Image.fromarray(image_array)
        
        temp_path = tempfile.mktemp(suffix=".png")
        image.save(temp_path)
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)
    except ImportError:
        # If PIL is not available, create a placeholder
        temp_path = tempfile.mktemp(suffix=".txt")
        with open(temp_path, "w") as f:
            f.write("test image placeholder")
        
        yield temp_path
        
        if os.path.exists(temp_path):
            os.remove(temp_path)


@pytest.fixture
def custom_nodes_dir(comfyui_path, temp_dir):
    """
    Create a temporary custom nodes directory for testing
    """
    custom_nodes_path = os.path.join(comfyui_path, "custom_nodes", "test_regression_nodes")
    os.makedirs(custom_nodes_path, exist_ok=True)
    
    yield custom_nodes_path
    
    # Cleanup
    if os.path.exists(custom_nodes_path):
        shutil.rmtree(custom_nodes_path, ignore_errors=True)
