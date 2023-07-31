import sys
import json
from typing import Dict, List, Union, Tuple, Any

sys.path.append('../')
# from execution import PromptExecutor
from nodes import NODE_CLASS_MAPPINGS


def read_json_file(file_path: str) -> dict:
    """
    Reads a JSON file and returns its contents as a dictionary.

    Args:
        file_path (str): The path to the JSON file.

    Returns:
        dict: The contents of the JSON file as a dictionary.
    """
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON format in file: {file_path}")
    

def determine_load_order(data: Dict[str, Dict[str, Union[Dict[str, Union[int, List[Union[str, int]]]], str]]]) -> List[Tuple[str, Dict[str, Union[Dict[str, Union[int, List[Union[str, int]]]], str]]]]:
    """Determine the load order of each key in the provided dictionary.

    Args:
    data (Dict[str, Dict[str, Union[Dict[str, Union[int, List[Union[str, int]]]], str]]]): 
    The dictionary for which to determine the load order.

    Returns:
    List[Tuple[str, Dict[str, Union[Dict[str, Union[int, List[Union[str, int]]]], str]]]]: 
    A list of tuples where each tuple contains a key and its corresponding dictionary, ordered by load order.
    """

    # Visited dictionary to keep track of visited nodes
    visited = {}
    load_order = []

    def dfs(key: str):
        """Depth-First Search function.

        Args:
        key (str): The key from which to start the DFS.

        Returns:
        None.
        """
        # Mark the node as visited
        visited[key] = True
        inputs = data[key]['inputs']
        
        for input_key, val in inputs.items():
            # Check if the input value is a list and not already visited
            if isinstance(val, list) and val[0] not in visited:
                dfs(val[0])
        
        # Add the key to the load order list
        load_order.append((key, data[key]))

    # Loop over each key in the data
    for key in data:
        # If the key is not visited, perform a DFS from that key
        if key not in visited:
            dfs(key)

    return load_order

def generate_code(obj: object, func: str, variable_name: str, **kwargs) -> str:
    """
    This function generates Python code for a function call.

    Args:
        obj (object): The object whose method is to be called.
        func (str): The function to be called.
        variable_name (str): The name of the variable that the function result should be assigned to.
        **kwargs: The keyword arguments for the function.

    Returns:
        str: The generated Python code.
    """
    # Get the class name of the object
    obj_name = obj.__class__.__name__

    # Convert the function arguments into a string
    # If the value is a string, it is surrounded by quotes
    # If the value is a dictionary and has key 'variable_name', its value is used as the arg value
    # For images argument and obj_name has 'SaveImage', '.detach' is appended at the end
    args = ', '.join(
        f'{key}="{value}"' if isinstance(value, str)
        else f'{key}={value["variable_name"]}.detach()' if key == 'images' and "SaveImage" in obj_name and isinstance(value, dict) and 'variable_name' in value
        else f'{key}={value["variable_name"]}' if isinstance(value, dict) and 'variable_name' in value
        else f'{key}={value}' for key, value in kwargs.items()
    )

    # Generate the Python code
    code = f'{variable_name} = {obj_name}().{func}({args})'

    return code




def update_inputs(inputs: Dict[str, Any], executed_variables: Dict[str, str]) -> Dict[str, Any]:
    """
    Update inputs based on the executed variables.

    Args:
        inputs (Dict[str, Any]): Inputs dictionary to update.
        executed_variables (Dict[str, str]): Dictionary storing executed variable names.

    Returns:
        Dict[str, Any]: Updated inputs dictionary.
    """
    for key in inputs.keys():
        if isinstance(inputs[key], list) and inputs[key][0] in executed_variables.keys():
            inputs[key] = {'variable_name': f"{executed_variables[inputs[key][0]]}[{inputs[key][1]}]"}
    return inputs

def generate_execution_code(load_order: List[Dict[str, Any]], filename: str = 'generated_code_workflow.py') -> str:
    """
    Generate the execution code based on the load order.
    
    This function will organize the necessary imports at the top, ensure the 
    code is formatted in a readable way, wrap it into a main function, and 
    save it as a .py file in the same directory.
    
    Args:
        load_order (List[Dict[str, Any]]): A list of dictionaries representing the
            load order. Each dictionary should contain keys 'inputs', 'class_type', and
            optionally other keys with corresponding values.
        filename (str, optional): The name of the Python file to which the code should be saved.
            Defaults to 'generated_code.py'.

    Returns:
        str: Generated execution code as a string.
    """
    # Collect the imports required and the code separately
    import_statements = set()
    executed_variables = {}
    code = []
    
    for idx, data in load_order:
        inputs = data['inputs']
        class_type = data['class_type']
        class_def = NODE_CLASS_MAPPINGS[class_type]()
        
        # Keep track of required imports
        import_statements.add(class_type)

        # Create executed variable and generate code
        executed_variables[idx] = f'{class_type.lower()}_{idx}'
        inputs = update_inputs(inputs, executed_variables)
        code.append(generate_code(class_def, class_def.FUNCTION, executed_variables[idx], **inputs))
        
    # Convert the import statements into code
    imports_code = [f"from nodes import {class_name}" for class_name in import_statements]
    
    # Combine import statements and code, and wrap them in a main function
    main_function_code = f"def main():\n\t" + '\n\t'.join(code)
    full_code = '\n'.join(['import sys\nsys.path.append("../")'] + imports_code + ['', main_function_code, '', 'if __name__ == "__main__":', '\tmain()'])
    
    # Save the code to a .py file
    with open(filename, 'w') as file:
        file.write(full_code)
        
    return full_code


if __name__ == '__main__':
    prompt = read_json_file('workflow_api.json')
    load_order = determine_load_order(prompt)
    code = generate_execution_code(load_order)
    print(code)
