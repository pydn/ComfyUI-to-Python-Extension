import glob
import inspect
import json
import logging
import os
import sys

import black

from typing import Dict, List, Any, Callable

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
            A list of tuples where each tuple contains a key, its corresponding dictionary, 
            and a boolean indicating whether or not the function is dependent on the output of
            a previous function, ordered by load order.
    """

    # Create a dictionary to keep track of visited nodes.
    visited = {}
    # Create a list to store the load order for functions
    load_order = []
    # Boolean to indicate whether or not the class is a loader class that should not be
    # reloaded during every loop
    is_loader = False

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
        load_order.append((key, data[key], is_loader))  

    # Load Loader keys first
    for key in data:
        class_def = NODE_CLASS_MAPPINGS[data[key]['class_type']]()
        if class_def.CATEGORY == 'loaders' or class_def.FUNCTION in ['encode'] or not any(isinstance(val, list) for val in data[key]['inputs'].values()):
            is_loader = True
            # If the key has not been visited, perform a DFS from that key.
            if key not in visited:
                dfs(key)

    # Reset is_loader bool
    is_loader = False
    # Loop over each key in the data.
    for key in data:
        # If the key has not been visited, perform a DFS from that key.
        if key not in visited:
            dfs(key)

    return load_order


def create_function_call_code(obj_name: str, func: str, variable_name: str, is_loader: bool, **kwargs) -> str:
    """
    This function generates Python code for a function call.

    Args:
        obj_name (str): The name of the initialized object.
        func (str): The function to be called.
        variable_name (str): The name of the variable that the function result should be assigned to.
        is_loader (bool): Determines the code indentation.
        **kwargs: The keyword arguments for the function.

    Returns:
        str: The generated Python code.
    """

    def format_arg(key: str, value: any) -> str:
        """Formats arguments based on key and value."""
        if key == 'noise_seed':
            return f'{key}=random.randint(1, 2**64)'
        elif isinstance(value, str):
            value = value.replace("\n", "\\n")
            return f'{key}="{value}"'
        elif key == 'images' and "saveimage" in obj_name and isinstance(value, dict) and 'variable_name' in value:
            return f'{key}={value["variable_name"]}.detach()'
        elif isinstance(value, dict) and 'variable_name' in value:
            return f'{key}={value["variable_name"]}'
        return f'{key}={value}'

    args = ', '.join(format_arg(key, value) for key, value in kwargs.items())

    # Generate the Python code
    code = f'{variable_name} = {obj_name}.{func}({args})\n'

    # If the code contains dependencies, indent the code because it will be placed inside
    # of a for loop
    if not is_loader:
        code = f'\t{code}'

    return code


def update_inputs(inputs: Dict, executed_variables: Dict) -> Dict:
    """
    Update inputs based on the executed variables.

    Args:
        inputs (Dict): Inputs dictionary to update.
        executed_variables (Dict): Dictionary storing executed variable names.

    Returns:
        Dict: Updated inputs dictionary.
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


def assemble_python_code(import_statements: set, loader_code: List[str], code: List[str], queue_size: int) -> str:
    """
    Generates final code string.

    Args:
        import_statements (set): A set of unique import statements
        code (List[str]): A list of code strings
        queue_size (int): Number of photos that will be generated by the script.

    Returns:
        final_code (str): Generated final code as a string
    """
    static_imports = ['import random']
    imports_code = [f"from nodes import {', '.join([class_name for class_name in import_statements])}" ]
    main_function_code = f"def main():\n\t" + '\n\t'.join(loader_code) + f'\n\n\tfor q in {range(queue_size)}:\n\t' + '\n\t'.join(code)
    final_code = '\n'.join(static_imports + ['import sys\nsys.path.append("../")'] + imports_code + ['', main_function_code, '', 'if __name__ == "__main__":', '\tmain()'])
    final_code = black.format_str(final_code, mode=black.Mode())


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


def get_function_parameters(func: Callable) -> List:
    """Get the names  of a function's parameters.

    Args:
        func (Callable): The function whose parameters we want to inspect.

    Returns:
        List: A list containing the names of the function's parameters.
    """
    signature = inspect.signature(func)
    parameters = {name: param.default if param.default != param.empty else None
                  for name, param in signature.parameters.items()}
    return list(parameters.keys())


def generate_workflow(load_order: List, filename: str = 'generated_code_workflow.py', queue_size: int = 10) -> str:
    """
    Generate the execution code based on the load order.

    Args:
        load_order (List): A list of tuples representing the load order.
        filename (str): The name of the Python file to which the code should be saved.
            Defaults to 'generated_code_workflow.py'.
        queue_size (int): The number of photos that will be created by the script.

    Returns:
        str: Generated execution code as a string.
    """

    # Create the necessary data structures to hold imports and generated code
    import_statements, executed_variables, loader_code, code = set(), {}, [], []
    # This dictionary will store the names of the objects that we have already initialized
    initialized_objects = {}

    # Loop over each dictionary in the load order list
    for idx, data, is_loader in load_order:

        # Generate class definition and inputs from the data
        inputs, class_type = data['inputs'], data['class_type']
        class_def = NODE_CLASS_MAPPINGS[class_type]()

        # If the class hasn't been initialized yet, initialize it and generate the import statements
        if class_type not in initialized_objects:
            class_type, import_statement, class_code = get_class_info(class_type)
            initialized_objects[class_type] = class_type.lower()
            import_statements.add(import_statement)
            loader_code.append(class_code)

        # Get all possible parameters for class_def
        class_def_params = get_function_parameters(getattr(class_def, class_def.FUNCTION))

        # Remove any keyword arguments from **inputs if they are not in class_def_params
        inputs = {key: value for key, value in inputs.items() if key in class_def_params}

        # Create executed variable and generate code
        executed_variables[idx] = f'{class_type.lower()}_{idx}'
        inputs = update_inputs(inputs, executed_variables)

        if is_loader:
            loader_code.append(create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_loader, **inputs))
        else:
            code.append(create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_loader, **inputs))

    # Generate final code by combining imports and code, and wrap them in a main function
    final_code = assemble_python_code(import_statements, loader_code, code, queue_size)

    # Save the code to a .py file
    write_code_to_file(filename, final_code)

    return final_code


def main(input, queue_size=10):
    """
    Main function to be executed.
    """
    # Load JSON data from the input file
    prompt = read_json_file(input)
    load_order = determine_load_order(prompt)
    output_file = input.replace('.json', '.py')
    code = generate_workflow(load_order, filename=output_file, queue_size=queue_size)
    logging.info(code)


if __name__ == '__main__':
    input = 'workflow_api.json'
    queue_size = 10
    main(input, queue_size)
