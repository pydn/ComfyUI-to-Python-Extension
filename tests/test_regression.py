"""
Regression tests for ComfyUI-to-Python-Extension

This test suite validates the core functionality including:
1. Simple local workflow - LoadImage -> SaveImage  
2. Custom nodes workflow - sync
3. Custom nodes workflow - async
"""
import pytest
import os
import json
import sys
import tempfile
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any
import asyncio

# Import our extension modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestComfyUIToPythonRegression:
    """Regression test suite for ComfyUI-to-Python-Extension"""
    
    def test_simple_workflow_load_save_image(self, comfyui_setup, temp_dir, test_image_path):
        """
        Test 1: Simple local workflow - LoadImage -> SaveImage

        This test creates a basic workflow that loads an image and saves it,
        then converts it to Python and validates the generated code.
        """
        # Import extension modules after ComfyUI setup
        from comfyui_to_python import ComfyUItoPython, FileHandler
        
        # Create a simple LoadImage -> SaveImage workflow
        workflow = {
            "1": {
                "inputs": {
                    "image": os.path.basename(test_image_path),
                    "upload": "image"
                },
                "class_type": "LoadImage",
                "_meta": {
                    "title": "Load Image"
                }
            },
            "2": {
                "inputs": {
                    "filename_prefix": "test_regression",
                    "images": ["1", 0]
                },
                "class_type": "SaveImage", 
                "_meta": {
                    "title": "Save Image"
                }
            }
        }
        
        # Convert workflow to Python
        output_file = os.path.join(temp_dir, "test_simple_workflow.py")
        
        converter = ComfyUItoPython(
            workflow=json.dumps(workflow),
            output_file=output_file,
            queue_size=1,
            needs_init_custom_nodes=False
        )
        
        # Verify the Python file was created
        assert os.path.exists(output_file), "Generated Python file should exist"
        
        # Read and validate the generated code
        with open(output_file, 'r') as f:
            generated_code = f.read()
        
        # Basic validation checks
        assert "LoadImage" in generated_code, "Generated code should contain LoadImage"
        assert "SaveImage" in generated_code, "Generated code should contain SaveImage"
        assert "async def main" in generated_code, "Generated code should have async main function"
        assert "torch.inference_mode" in generated_code, "Generated code should use inference mode"
        
        # Verify the code is syntactically valid Python
        try:
            compile(generated_code, output_file, 'exec')
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}")
        
        print(f"✅ Simple workflow test passed. Generated file: {output_file}")
    
    def test_sync_custom_nodes_workflow(self, comfyui_setup, temp_dir):
        """
        Test 2: Custom nodes workflow - sync

        This test creates a workflow using synchronous custom nodes
        and validates the generated Python code.
        """
        # Import extension modules after ComfyUI setup
        from comfyui_to_python import ComfyUItoPython, FileHandler
        
        # Register our custom nodes temporarily
        try:
            from tests.test_custom_nodes import NODE_CLASS_MAPPINGS as CUSTOM_NODE_MAPPINGS
            
            # Import ComfyUI's node mappings and add our custom nodes
            from nodes import NODE_CLASS_MAPPINGS
            original_mappings = NODE_CLASS_MAPPINGS.copy()
            NODE_CLASS_MAPPINGS.update(CUSTOM_NODE_MAPPINGS)
            
            # Create a sync custom nodes workflow
            workflow = {
                "1": {
                    "inputs": {
                        "text": "Hello from sync test!"
                    },
                    "class_type": "LoadTextSync",
                    "_meta": {
                        "title": "Load Text Sync"
                    }
                },
                "2": {
                    "inputs": {
                        "text": ["1", 0],
                        "filename_prefix": "sync_test_output"
                    },
                    "class_type": "SaveTextSync",
                    "_meta": {
                        "title": "Save Text Sync"
                    }
                }
            }
            
            # Convert workflow to Python
            output_file = os.path.join(temp_dir, "test_sync_workflow.py")
            
            converter = ComfyUItoPython(
                workflow=json.dumps(workflow),
                output_file=output_file,
                queue_size=1,
                needs_init_custom_nodes=False
            )
            
            # Verify the Python file was created
            assert os.path.exists(output_file), "Generated Python file should exist"
            
            # Read and validate the generated code
            with open(output_file, 'r') as f:
                generated_code = f.read()
            
            # Validation checks
            assert "LoadTextSync" in generated_code, "Generated code should contain LoadTextSync"
            assert "SaveTextSync" in generated_code, "Generated code should contain SaveTextSync"
            assert "NODE_CLASS_MAPPINGS" in generated_code, "Generated code should use NODE_CLASS_MAPPINGS for custom nodes"
            assert "Hello from sync test!" in generated_code, "Generated code should contain the test text"
            
            # Verify the code is syntactically valid Python
            try:
                compile(generated_code, output_file, 'exec')
            except SyntaxError as e:
                pytest.fail(f"Generated code has syntax errors: {e}")
            
            print(f"✅ Sync custom nodes test passed. Generated file: {output_file}")
            
        finally:
            # Restore original node mappings
            NODE_CLASS_MAPPINGS.clear()
            NODE_CLASS_MAPPINGS.update(original_mappings)
    
    def test_async_custom_nodes_workflow(self, comfyui_setup, temp_dir):
        """
        Test 3: Custom nodes workflow - async

        This test creates a workflow using asynchronous custom nodes
        and validates the generated Python code handles async operations correctly.
        """
        # Import extension modules after ComfyUI setup
        from comfyui_to_python import ComfyUItoPython, FileHandler
        
        # Register our custom nodes temporarily
        try:
            from tests.test_custom_nodes import NODE_CLASS_MAPPINGS as CUSTOM_NODE_MAPPINGS
            
            # Import ComfyUI's node mappings and add our custom nodes
            from nodes import NODE_CLASS_MAPPINGS
            original_mappings = NODE_CLASS_MAPPINGS.copy()
            NODE_CLASS_MAPPINGS.update(CUSTOM_NODE_MAPPINGS)
            
            # Create an async custom nodes workflow
            workflow = {
                "1": {
                    "inputs": {
                        "text": "Hello from async test!",
                        "delay": 0.1
                    },
                    "class_type": "LoadTextAsync",
                    "_meta": {
                        "title": "Load Text Async"
                    }
                },
                "2": {
                    "inputs": {
                        "text": ["1", 0],
                        "filename_prefix": "async_test_output",
                        "delay": 0.1
                    },
                    "class_type": "SaveTextAsync",
                    "_meta": {
                        "title": "Save Text Async"
                    }
                }
            }
            
            # Convert workflow to Python
            output_file = os.path.join(temp_dir, "test_async_workflow.py")
            
            converter = ComfyUItoPython(
                workflow=json.dumps(workflow),
                output_file=output_file,
                queue_size=1,
                needs_init_custom_nodes=False
            )
            
            # Verify the Python file was created
            assert os.path.exists(output_file), "Generated Python file should exist"
            
            # Read and validate the generated code
            with open(output_file, 'r') as f:
                generated_code = f.read()
            
            # Validation checks
            assert "LoadTextAsync" in generated_code, "Generated code should contain LoadTextAsync"
            assert "SaveTextAsync" in generated_code, "Generated code should contain SaveTextAsync"
            assert "await " in generated_code, "Generated code should contain await statements for async functions"
            assert "NODE_CLASS_MAPPINGS" in generated_code, "Generated code should use NODE_CLASS_MAPPINGS for custom nodes"
            assert "Hello from async test!" in generated_code, "Generated code should contain the test text"
            
            # Verify the code is syntactically valid Python
            try:
                compile(generated_code, output_file, 'exec')
            except SyntaxError as e:
                pytest.fail(f"Generated code has syntax errors: {e}")
            
            print(f"✅ Async custom nodes test passed. Generated file: {output_file}")
            
        finally:
            # Restore original node mappings
            NODE_CLASS_MAPPINGS.clear()
            NODE_CLASS_MAPPINGS.update(original_mappings)
    
    def test_parameterized_workflow(self, comfyui_setup, temp_dir):
        """
        Test 4: Parameterized workflow generation

        This test validates that workflows can be parameterized properly.
        """
        # Import extension modules after ComfyUI setup
        from comfyui_to_python import ComfyUItoPython, FileHandler
        
        try:
            from tests.test_custom_nodes import NODE_CLASS_MAPPINGS as CUSTOM_NODE_MAPPINGS
            
            # Import ComfyUI's node mappings and add our custom nodes
            from nodes import NODE_CLASS_MAPPINGS
            original_mappings = NODE_CLASS_MAPPINGS.copy()
            NODE_CLASS_MAPPINGS.update(CUSTOM_NODE_MAPPINGS)
            
            # Create a workflow
            workflow = {
                "1": {
                    "inputs": {
                        "text": "Default text"
                    },
                    "class_type": "LoadTextSync",
                    "_meta": {
                        "title": "Load Text Sync"
                    }
                },
                "2": {
                    "inputs": {
                        "text": ["1", 0],
                        "filename_prefix": "param_test"
                    },
                    "class_type": "SaveTextSync",
                    "_meta": {
                        "title": "Save Text Sync"
                    }
                }
            }
            
            # Create parameter mappings
            param_mappings = {
                "input_text": [["1", "text"]],
                "output_prefix": [["2", "filename_prefix"]]
            }
            
            # Write parameter mappings to file
            param_file = os.path.join(temp_dir, "param_mappings.json")
            with open(param_file, 'w') as f:
                json.dump(param_mappings, f)
            
            # Convert workflow to Python with parameters
            output_file = os.path.join(temp_dir, "test_param_workflow.py")
            
            converter = ComfyUItoPython(
                workflow=json.dumps(workflow),
                output_file=output_file,
                queue_size=1,
                needs_init_custom_nodes=False,
                param_mappings_file=param_file
            )
            
            # Verify the Python file was created
            assert os.path.exists(output_file), "Generated Python file should exist"
            
            # Read and validate the generated code
            with open(output_file, 'r') as f:
                generated_code = f.read()
            
            # Validation checks for parameterization
            assert "input_text=None" in generated_code, "Generated code should have input_text parameter"
            assert "output_prefix=None" in generated_code, "Generated code should have output_prefix parameter"
            assert "input_text or" in generated_code, "Generated code should use parameter with fallback"
            
            print(f"✅ Parameterized workflow test passed. Generated file: {output_file}")
            
        finally:
            # Restore original node mappings
            NODE_CLASS_MAPPINGS.clear()
            NODE_CLASS_MAPPINGS.update(original_mappings)
    
    def test_caching_functionality(self, comfyui_setup, temp_dir):
        """
        Test 5: Node caching functionality

        This test validates that constant nodes are properly cached.
        """
        # Import extension modules after ComfyUI setup
        from comfyui_to_python import ComfyUItoPython, FileHandler
        
        try:
            from tests.test_custom_nodes import NODE_CLASS_MAPPINGS as CUSTOM_NODE_MAPPINGS
            
            # Import ComfyUI's node mappings and add our custom nodes
            from nodes import NODE_CLASS_MAPPINGS
            original_mappings = NODE_CLASS_MAPPINGS.copy()
            NODE_CLASS_MAPPINGS.update(CUSTOM_NODE_MAPPINGS)
            
            # Create a workflow with constant nodes that should be cached
            workflow = {
                "1": {
                    "inputs": {
                        "text": "Constant text that should be cached"
                    },
                    "class_type": "LoadTextSync",
                    "_meta": {
                        "title": "Load Constant Text"
                    }
                },
                "2": {
                    "inputs": {
                        "text": ["1", 0],
                        "filename_prefix": "cache_test"
                    },
                    "class_type": "SaveTextSync",
                    "_meta": {
                        "title": "Save Text"
                    }
                }
            }
            
            # Convert workflow to Python
            output_file = os.path.join(temp_dir, "test_cache_workflow.py")
            
            converter = ComfyUItoPython(
                workflow=json.dumps(workflow),
                output_file=output_file,
                queue_size=5,  # Multiple iterations to test caching
                needs_init_custom_nodes=False
            )
            
            # Verify the Python file was created
            assert os.path.exists(output_file), "Generated Python file should exist"
            
            # Read and validate the generated code
            with open(output_file, 'r') as f:
                generated_code = f.read()
            
            # Validation checks for caching
            assert "_NODE_CACHE" in generated_code, "Generated code should include node cache"
            assert "setdefault" in generated_code, "Generated code should use cache setdefault"
            
            print(f"✅ Caching functionality test passed. Generated file: {output_file}")
            
        finally:
            # Restore original node mappings
            NODE_CLASS_MAPPINGS.clear()
            NODE_CLASS_MAPPINGS.update(original_mappings)


class TestComfyUIDiscovery:
    """Test auto-discovery of ComfyUI installation"""
    
    def test_auto_find_comfyui(self, comfyui_path):
        """Test that ComfyUI installation can be automatically discovered"""
        assert comfyui_path is not None, "ComfyUI path should be found"
        assert os.path.isdir(comfyui_path), "ComfyUI path should be a directory"
        assert os.path.exists(os.path.join(comfyui_path, "main.py")), "ComfyUI should have main.py"
        assert os.path.exists(os.path.join(comfyui_path, "nodes.py")), "ComfyUI should have nodes.py"
        
        print(f"✅ ComfyUI auto-discovery test passed. Found at: {comfyui_path}")
    
    def test_utils_find_path(self):
        """Test the find_path utility function"""
        # Import extension modules
        from comfyui_to_python_utils import find_path
        
        # Test finding a directory that should exist
        current_dir = os.getcwd()
        parent_dir = os.path.dirname(current_dir)
        
        # Should find the current directory when searching from parent
        found_path = find_path(os.path.basename(current_dir), parent_dir)
        assert found_path is not None, "find_path should find existing directory"
        assert os.path.samefile(found_path, current_dir), "find_path should return correct path"
        
        print("✅ find_path utility test passed")


if __name__ == "__main__":
    # Run tests with pytest when executed directly
    pytest.main([__file__, "-v"])
