"""
Isolated tests for ComfyUI-to-Python-Extension that avoid import conflicts

This test module runs tests in isolation to avoid protocol module conflicts.
"""
import pytest
import os


# Test root directory path
TEST_ROOT = os.path.dirname(os.path.dirname(__file__))


class TestScriptExecution:
    """Test script execution functionality"""
    
    def test_python_syntax_of_main_modules(self):
        """Test that main Python modules have valid syntax"""
        main_modules = [
            "comfyui_to_python.py",
            "comfyui_to_python_utils.py"
        ]
        
        for module_name in main_modules:
            module_path = os.path.join(TEST_ROOT, module_name)
            if os.path.exists(module_path):
                with open(module_path, 'r') as f:
                    content = f.read()
                
                try:
                    compile(content, module_path, 'exec')
                    print(f"✅ {module_name} has valid Python syntax")
                except SyntaxError as e:
                    pytest.fail(f"{module_name} has syntax errors: {e}")
            else:
                pytest.fail(f"Required module {module_name} not found")


if __name__ == "__main__":
    # Run tests with pytest when executed directly
    pytest.main([__file__, "-v"])
