import glob
import json
import logging
import os
from typing import Dict, List, Any
import sys

sys.path.append('../')

from nodes import NODE_CLASS_MAPPINGS

logging.basicConfig(level=logging.INFO)


def read_json_file(file_path: str) -> dict:
    """
    Reads a JSON file and returns its contents as a dictionary.

    Args:
        file_path (str): The path to the JSON file.

    Returns:
        dict: The contents of the JSON file as a dictionary.

    Raises:
        FileNotFoundError: If the file is not found, it lists all JSON files in the directory of the file path.
        ValueError: If the file is not a valid JSON.
    """

    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
        return data

    except FileNotFoundError:
        # Get the directory from the file_path
        directory = os.path.dirname(file_path)

        # If the directory is an empty string (which means file is in the current directory),
        # get the current working directory
        if not directory:
            directory = os.getcwd()

        # Find all JSON files in the directory
        json_files = glob.glob(f"{directory}/*.json")

        # Format the list of JSON files as a string
        json_files_str = "\n".join(json_files)

        raise FileNotFoundError(f"\n\nFile not found: {file_path}. JSON files in the directory:\n{json_files_str}")

    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON format in file: {file_path}")
    

def determine_load_order(data: Dict) -> List:
    """
    Determine the load order of each key in the provided dictionary. This code will place the 
    nodes without node dependencies first, then ensure that any node whose result is used
    in another node will be added to the list in the order it should be executed.

    Args:
        data (Dict): 
            The dictionary for which to determine the load order.

    Returns:
        List: 
            A list of tuples where each tuple contains a key and its corresponding dictionary, ordered by load order.
    """

    # Create a dictionary to keep track of visited nodes.
    visited = {}
    # Create a list to store the load order.
    load_order = []

    def dfs(key: str) -> None:
        """
        Depth-First Search function.

        Args:
            key (str): The key from which to start the DFS.

        Returns:
            None
        """
        # Mark the node as visited.
        visited[key] = True
        inputs = data[key]['inputs']

        # Loop over each input key.
        for input_key, val in inputs.items():
            # If the value is a list and the first item in the list (which should be a key) 
            # has not been visited yet, then recursively apply dfs on the dependency.
            if isinstance(val, list) and val[0] not in visited:
                dfs(val[0])  

        # Add the key and its corresponding data to the load order list.
        load_order.append((key, data[key]))  

    # Loop over each key in the data.
    for key in data:
        # Check if the key has dependencies
        if not any(isinstance(val, list) for val in data[key]['inputs'].values()):
            # Add keys with no dependencies to load order and mark as visited
            load_order.append((key, data[key]))
            visited[key] = True

    # Loop over each key in the data.
    for key in data:
        # If the key has not been visited, perform a DFS from that key.
        if key not in visited:
            dfs(key)

    return load_order


def create_function_call_code(obj_name: str, func: str, variable_name: str, **kwargs) -> str:
    """
    This function generates Python code for a function call.

    Args:
        obj_name (str): The name of the initialized object.
        func (str): The function to be called.
        variable_name (str): The name of the variable that the function result should be assigned to.
        **kwargs: The keyword arguments for the function.

    Returns:
        str: The generated Python code.
    """
    # Convert the function arguments into a string
    # If the value is a string, it is surrounded by quotes
    # If the value is a dictionary and has key 'variable_name', its value is used as the arg value
    # For images argument and obj_name has 'SaveImage', '.detach' is appended at the end
    args = ', '.join(
        f'{key}="{value}"' if isinstance(value, str)
        else f'{key}={value["variable_name"]}.detach()' if key == 'images' and "saveimage" in obj_name and isinstance(value, dict) and 'variable_name' in value
        else f'{key}={value["variable_name"]}' if isinstance(value, dict) and 'variable_name' in value
        else f'{key}={value}' for key, value in kwargs.items()
    )

    # Generate the Python code
    code = f'{variable_name} = {obj_name}.{func}({args})'

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


def get_class_info(class_type: str) -> (str, str, str):
    """
    Generates and returns necessary information about class type.

    Args:
        class_type (str): Class type

    Returns:
        class_type (str): Updated class type
        import_statement (str): Import statement string
        class_code (str): Class initialization code
    """
    # If the class is 'VAEDecode', adjust the class name
    if class_type == 'VAEDecode':
        class_type = 'VAEDecodeTiled'
    
    import_statement = class_type
    class_code = f'{class_type.lower()} = {class_type}()'

    return class_type, import_statement, class_code


def assemble_python_code(import_statements: set, code: List[str]) -> str:
    """
    Generates final code string.

    Args:
        import_statements (set): A set of unique import statements
        code (List[str]): A list of code strings

    Returns:
        final_code (str): Generated final code as a string
    """
    imports_code = [f"from nodes import {class_name}" for class_name in import_statements]
    main_function_code = f"def main():\n\t" + '\n\t'.join(code)
    final_code = '\n'.join(['import sys\nsys.path.append("../")'] + imports_code + ['', main_function_code, '', 'if __name__ == "__main__":', '\tmain()'])

    return final_code


def write_code_to_file(filename: str, code: str) -> None:
    """
    Writes given code to a .py file. If the directory does not exist, it creates it.

    Args:
        filename (str): The name of the Python file to save the code to.
        code (str): The code to save.
    """

    # Extract directory from the filename
    directory = os.path.dirname(filename)

    # If the directory does not exist, create it
    if directory and not os.path.exists(directory):
        os.makedirs(directory)

    # Save the code to a .py file
    with open(filename, 'w') as file:
        file.write(code)


def generate_workflow(load_order: List, filename: str = 'generated_code_workflow.py') -> str:
    """
    Generate the execution code based on the load order.

    Args:
        load_order (List): A list of tuples representing the load order.
        filename (str): The name of the Python file to which the code should be saved.
            Defaults to 'generated_code_workflow.py'.

    Returns:
        str: Generated execution code as a string.
    """

    # Create the necessary data structures to hold imports and generated code
    import_statements, executed_variables, code = set(), {}, []
    # This dictionary will store the names of the objects that we have already initialized
    initialized_objects = {}

    # Loop over each dictionary in the load order list
    for idx, data in load_order:

        # Generate class definition and inputs from the data
        inputs, class_type = data['inputs'], data['class_type']
        class_def = NODE_CLASS_MAPPINGS[class_type]()

        # If the class hasn't been initialized yet, initialize it and generate the import statements
        if class_type not in initialized_objects:
            class_type, import_statement, class_code = get_class_info(class_type)
            initialized_objects[class_type] = class_type.lower()
            import_statements.add(import_statement)
            code.append(class_code)

        # Create executed variable and generate code
        executed_variables[idx] = f'{class_type.lower()}_{idx}'
        inputs = update_inputs(inputs, executed_variables)
        code.append(create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], **inputs))

    # Generate final code by combining imports and code, and wrap them in a main function
    final_code = assemble_python_code(import_statements, code)

    # Save the code to a .py file
    write_code_to_file(filename, final_code)

    return final_code


if __name__ == '__main__':
    input_file = 'workflow_api_inpainting.json'
    prompt = read_json_file(input_file)
    load_order = determine_load_order(prompt)
    output_file = input_file.replace('.json', '.py')
    code = generate_workflow(load_order, filename=output_file)
    logging.info(code)
