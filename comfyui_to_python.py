import copy
import glob
import inspect
import json
import os
import random
import sys
import re
from typing import Dict, List, Any, Callable, Tuple

import black


from utils import import_custom_nodes, find_path, add_comfyui_directory_to_sys_path, add_extra_model_paths, get_value_at_index

sys.path.append('../')
from nodes import NODE_CLASS_MAPPINGS


class FileHandler:
    """Handles reading and writing files.

    This class provides methods to read JSON data from an input file and write code to an output file.
    """

    @staticmethod
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

    @staticmethod
    def write_code_to_file(file_path: str, code: str) -> None:
        """Write the specified code to a Python file.

        Args:
            file_path (str): The path to the Python file.
            code (str): The code to write to the file.

        Returns:
            None
        """
        # Extract directory from the filename
        directory = os.path.dirname(file_path)

        # If the directory does not exist, create it
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        # Save the code to a .py file
        with open(file_path, 'w') as file:
            file.write(code)


class LoadOrderDeterminer:
    """Determine the load order of each key in the provided dictionary.

    This class places the nodes without node dependencies first, then ensures that any node whose
    result is used in another node will be added to the list in the order it should be executed.

    Attributes:
        data (Dict): The dictionary for which to determine the load order.
        node_class_mappings (Dict): Mappings of node classes.
    """

    def __init__(self, data: Dict, node_class_mappings: Dict):
        """Initialize the LoadOrderDeterminer with the given data and node class mappings.

        Args:
            data (Dict): The dictionary for which to determine the load order.
            node_class_mappings (Dict): Mappings of node classes.
        """
        self.data = data
        self.node_class_mappings = node_class_mappings
        self.visited = {}
        self.load_order = []
        self.is_special_function = False

    def determine_load_order(self) -> List[Tuple[str, Dict, bool]]:
        """Determine the load order for the given data.

        Returns:
            List[Tuple[str, Dict, bool]]: A list of tuples representing the load order.
        """
        self._load_special_functions_first()
        self.is_special_function = False
        for key in self.data:
            if key not in self.visited:
                self._dfs(key)
        return self.load_order

    def _dfs(self, key: str) -> None:
        """Depth-First Search function to determine the load order.

        Args:
            key (str): The key from which to start the DFS.

        Returns:
            None
        """
        # Mark the node as visited.
        self.visited[key] = True
        inputs = self.data[key]['inputs']
        # Loop over each input key.
        for input_key, val in inputs.items():
            # If the value is a list and the first item in the list has not been visited yet,
            # then recursively apply DFS on the dependency.
            if isinstance(val, list) and val[0] not in self.visited:
                self._dfs(val[0])
        # Add the key and its corresponding data to the load order list.
        self.load_order.append((key, self.data[key], self.is_special_function))

    def _load_special_functions_first(self) -> None:
        """Load functions without dependencies, loaderes, and encoders first.

        Returns:
            None
        """
        # Iterate over each key in the data to check for loader keys.
        for key in self.data:
            class_def = self.node_class_mappings[self.data[key]['class_type']]()
            # Check if the class is a loader class or meets specific conditions.
            if (class_def.CATEGORY == 'loaders' or 
                class_def.FUNCTION in ['encode'] or 
                not any(isinstance(val, list) for val in self.data[key]['inputs'].values())):
                self.is_special_function = True
                # If the key has not been visited, perform a DFS from that key.
                if key not in self.visited:
                    self._dfs(key)


class CodeGenerator:
    """Generates Python code for a workflow based on the load order.

    Attributes:
        node_class_mappings (Dict): Mappings of node classes.
        base_node_class_mappings (Dict): Base mappings of node classes.
    """

    def __init__(self, node_class_mappings: Dict, base_node_class_mappings: Dict):
        """Initialize the CodeGenerator with given node class mappings.

        Args:
            node_class_mappings (Dict): Mappings of node classes.
            base_node_class_mappings (Dict): Base mappings of node classes.
        """
        self.node_class_mappings = node_class_mappings
        self.base_node_class_mappings = base_node_class_mappings

    def generate_workflow(self, load_order: List, filename: str = 'generated_code_workflow.py', queue_size: int = 10) -> str:
        """Generate the execution code based on the load order.

        Args:
            load_order (List): A list of tuples representing the load order.
            filename (str): The name of the Python file to which the code should be saved.
                Defaults to 'generated_code_workflow.py'.
            queue_size (int): The number of photos that will be created by the script.

        Returns:
            str: Generated execution code as a string.
        """
        # Create the necessary data structures to hold imports and generated code
        import_statements, executed_variables, special_functions_code, code = set(['NODE_CLASS_MAPPINGS']), {}, [], []
        # This dictionary will store the names of the objects that we have already initialized
        initialized_objects = {}

        custom_nodes = False
        # Loop over each dictionary in the load order list
        for idx, data, is_special_function in load_order:

            # Generate class definition and inputs from the data
            inputs, class_type = data['inputs'], data['class_type']
            class_def = self.node_class_mappings[class_type]()

            # If the class hasn't been initialized yet, initialize it and generate the import statements
            if class_type not in initialized_objects:
                # No need to use preview image nodes since we are executing the script in a terminal
                if class_type == 'PreviewImage':
                    continue

                class_type, import_statement, class_code = self.get_class_info(class_type)
                initialized_objects[class_type] = self.clean_variable_name(class_type)
                if class_type in self.base_node_class_mappings.keys():
                    import_statements.add(import_statement)
                if class_type not in self.base_node_class_mappings.keys():
                    custom_nodes = True
                special_functions_code.append(class_code)

            # Get all possible parameters for class_def
            class_def_params = self.get_function_parameters(getattr(class_def, class_def.FUNCTION))

            # Remove any keyword arguments from **inputs if they are not in class_def_params
            inputs = {key: value for key, value in inputs.items() if key in class_def_params}
            # Deal with hidden variables
            if 'unique_id' in class_def_params:
                inputs['unique_id'] = random.randint(1, 2**64)

            # Create executed variable and generate code
            executed_variables[idx] = f'{self.clean_variable_name(class_type)}_{idx}'
            inputs = self.update_inputs(inputs, executed_variables)
            
            if is_special_function:
                special_functions_code.append(self.create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_special_function, **inputs))
            else:
                code.append(self.create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_special_function, **inputs))

        # Generate final code by combining imports and code, and wrap them in a main function
        final_code = self.assemble_python_code(import_statements, special_functions_code, code, queue_size, custom_nodes)

        return final_code

    def create_function_call_code(self, obj_name: str, func: str, variable_name: str, is_special_function: bool, **kwargs) -> str:
        """Generate Python code for a function call.

        Args:
            obj_name (str): The name of the initialized object.
            func (str): The function to be called.
            variable_name (str): The name of the variable that the function result should be assigned to.
            is_special_function (bool): Determines the code indentation.
            **kwargs: The keyword arguments for the function.

        Returns:
            str: The generated Python code.
        """
        args = ', '.join(self.format_arg(key, value) for key, value in kwargs.items())

        # Generate the Python code
        code = f'{variable_name} = {obj_name}.{func}({args})\n'

        # If the code contains dependencies and is not a loader or encoder, indent the code because it will be placed inside
        # of a for loop
        if not is_special_function:
            code = f'\t{code}'

        return code

    def format_arg(self, key: str, value: any) -> str:
        """Formats arguments based on key and value.

        Args:
            key (str): Argument key.
            value (any): Argument value.

        Returns:
            str: Formatted argument as a string.
        """
        if key == 'noise_seed' or key == 'seed':
            return f'{key}=random.randint(1, 2**64)'
        elif isinstance(value, str):
            value = value.replace("\n", "\\n").replace('"', "'")
            return f'{key}="{value}"'
        elif isinstance(value, dict) and 'variable_name' in value:
            return f'{key}={value["variable_name"]}'
        return f'{key}={value}'

    def assemble_python_code(self, import_statements: set, speical_functions_code: List[str], code: List[str], queue_size: int, custom_nodes=False) -> str:
        """Generates the final code string.

        Args:
            import_statements (set): A set of unique import statements.
            speical_functions_code (List[str]): A list of special functions code strings.
            code (List[str]): A list of code strings.
            queue_size (int): Number of photos that will be generated by the script.
            custom_nodes (bool): Whether to include custom nodes in the code.

        Returns:
            str: Generated final code as a string.
        """
        # Get the source code of the utils functions as a string
        func_strings = []
        for func in [get_value_at_index, find_path, add_comfyui_directory_to_sys_path, add_extra_model_paths]:
            func_strings.append(f'\n{inspect.getsource(func)}')
        # Define static import statements required for the script
        static_imports = ['import os', 'import random', 'import sys', 'from typing import Sequence, Mapping, Any, Union', 
                          'import torch'] + func_strings + ['\n\nadd_comfyui_directory_to_sys_path()\nadd_extra_model_paths()\n']
        # Check if custom nodes should be included
        if custom_nodes:
            static_imports.append(f'\n{inspect.getsource(import_custom_nodes)}\n')
            custom_nodes = 'import_custom_nodes()\n\t'
        else:
            custom_nodes = ''
        # Create import statements for node classes
        imports_code = [f"from nodes import {', '.join([class_name for class_name in import_statements])}" ]
        # Assemble the main function code, including custom nodes if applicable
        main_function_code = "def main():\n\t" + f'{custom_nodes}with torch.inference_mode():\n\t\t' + '\n\t\t'.join(speical_functions_code) \
            + f'\n\n\t\tfor q in range({queue_size}):\n\t\t' + '\n\t\t'.join(code)
        # Concatenate all parts to form the final code
        final_code = '\n'.join(static_imports + imports_code + ['', main_function_code, '', 'if __name__ == "__main__":', '\tmain()'])
        # Format the final code according to PEP 8 using the Black library
        final_code = black.format_str(final_code, mode=black.Mode())

        return final_code
    
    def get_class_info(self, class_type: str) -> Tuple[str, str, str]:
        """Generates and returns necessary information about class type.

        Args:
            class_type (str): Class type.

        Returns:
            Tuple[str, str, str]: Updated class type, import statement string, class initialization code.
        """
        import_statement = class_type
        variable_name = self.clean_variable_name(class_type)
        if class_type in self.base_node_class_mappings.keys():
            class_code = f'{variable_name} = {class_type.strip()}()'
        else:
            class_code = f'{variable_name} = NODE_CLASS_MAPPINGS["{class_type}"]()'

        return class_type, import_statement, class_code
    
    @staticmethod
    def clean_variable_name(class_type: str) -> str:
        """
        Remove any characters from variable name that could cause errors running the Python script.

        Args:
            class_type (str): Class type.

        Returns:
            str: Cleaned variable name with no special characters or spaces
        """
        # Convert to lowercase and replace spaces with underscores
        clean_name = class_type.lower().strip().replace("-", "_").replace(" ", "_")
        
        # Remove characters that are not letters, numbers, or underscores
        clean_name = re.sub(r'[^a-z0-9_]', '', clean_name)
        
        # Ensure that it doesn't start with a number
        if clean_name[0].isdigit():
            clean_name = "_" + clean_name
        
        return clean_name

    def get_function_parameters(self, func: Callable) -> List:
        """Get the names of a function's parameters.

        Args:
            func (Callable): The function whose parameters we want to inspect.

        Returns:
            List: A list containing the names of the function's parameters.
        """
        signature = inspect.signature(func)
        parameters = {name: param.default if param.default != param.empty else None
                    for name, param in signature.parameters.items()}
        return list(parameters.keys())  

    def update_inputs(self, inputs: Dict, executed_variables: Dict) -> Dict:
        """Update inputs based on the executed variables.

        Args:
            inputs (Dict): Inputs dictionary to update.
            executed_variables (Dict): Dictionary storing executed variable names.

        Returns:
            Dict: Updated inputs dictionary.
        """
        for key in inputs.keys():
            if isinstance(inputs[key], list) and inputs[key][0] in executed_variables.keys():
                inputs[key] = {'variable_name': f"get_value_at_index({executed_variables[inputs[key][0]]}, {inputs[key][1]})"}
        return inputs
    

class ComfyUItoPython:
    """Main workflow to generate Python code from a workflow_api.json file.

    Attributes:
        input_file (str): Path to the input JSON file.
        output_file (str): Path to the output Python file.
        queue_size (int): The number of photos that will be created by the script.
        node_class_mappings (Dict): Mappings of node classes.
        base_node_class_mappings (Dict): Base mappings of node classes.
    """

    def __init__(self, input_file: str, output_file: str, queue_size: int = 10, node_class_mappings: Dict = NODE_CLASS_MAPPINGS):
        """Initialize the ComfyUItoPython class with the given parameters.

        Args:
            input_file (str): Path to the input JSON file.
            output_file (str): Path to the output Python file.
            queue_size (int): The number of times a workflow will be executed by the script. Defaults to 10.
            node_class_mappings (Dict): Mappings of node classes. Defaults to NODE_CLASS_MAPPINGS.
        """
        self.input_file = input_file
        self.output_file = output_file
        self.queue_size = queue_size
        self.node_class_mappings = node_class_mappings
        self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)
        self.execute()

    def execute(self):
        """Execute the main workflow to generate Python code.

        Returns:
            None
        """
        # Step 1: Import all custom nodes
        import_custom_nodes()

        # Step 2: Read JSON data from the input file
        data = FileHandler.read_json_file(self.input_file)

        # Step 3: Determine the load order
        load_order_determiner = LoadOrderDeterminer(data, self.node_class_mappings)
        load_order = load_order_determiner.determine_load_order()

        # Step 4: Generate the workflow code
        code_generator = CodeGenerator(self.node_class_mappings, self.base_node_class_mappings)
        generated_code = code_generator.generate_workflow(load_order, filename=self.output_file, queue_size=self.queue_size)

        # Step 5: Write the generated code to a file
        FileHandler.write_code_to_file(self.output_file, generated_code)

        print(f"Code successfully generated and written to {self.output_file}")


if __name__ == '__main__':
    # Update class parameters here
    input_file = 'workflow_api.json'
    output_file = 'workflow_api.py'
    queue_size = 10

    # Convert ComfyUI workflow to Python
    ComfyUItoPython(input_file=input_file, output_file=output_file, queue_size=queue_size)
