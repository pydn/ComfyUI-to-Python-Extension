import copy
import inspect
import logging
import os
import sys

import black

from typing import Dict, List, Any, Callable

from utils import import_custom_nodes, read_json_file, write_code_to_file, add_comfyui_directories_to_sys_path


sys.path.append('../')

from nodes import NODE_CLASS_MAPPINGS


logging.basicConfig(level=logging.INFO)

    

class ComfyUItoPython:
    def __init__(self, input='workflow_api.json', queue_size=10):
        self.input = input
        self.queue_size = queue_size
        self.BASE_NODE_CLASS_MAPPINGS = copy.deepcopy(NODE_CLASS_MAPPINGS)
        self.generate_code()

    def generate_code(self):
        """
        Main function to be executed.
        """
        import_custom_nodes()
        # Load JSON data from the input file
        prompt = read_json_file(self.input)
        load_order = self.determine_load_order(prompt)
        output_file = self.input.replace('.json', '.py')
        code = self.generate_workflow(load_order, filename=output_file, queue_size=self.queue_size)
        logging.info(code)

    def determine_load_order(self, data: Dict) -> List:
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


    def create_function_call_code(self, obj_name: str, func: str, variable_name: str, is_loader: bool, **kwargs) -> str:
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
            if key == 'noise_seed' or key == 'seed':
                return f'{key}=random.randint(1, 2**64)'
            elif isinstance(value, str):
                value = value.replace("\n", "\\n").replace('"', "'")
                return f'{key}="{value}"'
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


    def update_inputs(self, inputs: Dict, executed_variables: Dict) -> Dict:
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
                inputs[key] = {'variable_name': f"get_value_at_index({executed_variables[inputs[key][0]]}, {inputs[key][1]})"}
        return inputs


    def get_class_info(self, class_type: str) -> (str, str, str):
        """
        Generates and returns necessary information about class type.

        Args:
            class_type (str): Class type

        Returns:
            class_type (str): Updated class type
            import_statement (str): Import statement string
            class_code (str): Class initialization code
        """
        import_statement = class_type
        if class_type in self.BASE_NODE_CLASS_MAPPINGS.keys():
            class_code = f'{class_type.lower()} = {class_type}()'
        else:
            class_code = f'{class_type.lower()} = NODE_CLASS_MAPPINGS["{class_type}"]()'

        return class_type, import_statement, class_code


    def assemble_python_code(self, import_statements: set, loader_code: List[str], code: List[str], queue_size: int, custom_nodes=False) -> str:
        """
        Generates final code string.

        Args:
            import_statements (set): A set of unique import statements
            code (List[str]): A list of code strings
            queue_size (int): Number of photos that will be generated by the script.
            custom_nodes (bool): Whether to include custom nodes in the code.

        Returns:
            final_code (str): Generated final code as a string
        """
        # Get the source code of the function as a string
        add_comfyui_directories_to_sys_path_code = inspect.getsource(add_comfyui_directories_to_sys_path)
        # Define static import statements required for the script
        static_imports = ['import os', 'import random', 'import sys', 'import torch', f'\n{add_comfyui_directories_to_sys_path_code}', 
                        '\n\nadd_comfyui_directories_to_sys_path()']
        # Check if custom nodes should be included
        if custom_nodes:
            static_imports.append('\nfrom utils import import_custom_nodes, get_value_at_index\n')
            custom_nodes = 'import_custom_nodes()\n\t'
        else:
            custom_nodes = ''
        # Create import statements for node classes
        imports_code = [f"from nodes import {', '.join([class_name for class_name in import_statements])}" ]
        # Assemble the main function code, including custom nodes if applicable
        main_function_code = "def main():\n\t" + f'{custom_nodes}with torch.inference_mode():\n\t\t' + '\n\t\t'.join(loader_code) \
            + f'\n\n\t\tfor q in range({queue_size}):\n\t\t' + '\n\t\t'.join(code)
        # Concatenate all parts to form the final code
        final_code = '\n'.join(static_imports + imports_code + ['', main_function_code, '', 'if __name__ == "__main__":', '\tmain()'])
        # Format the final code according to PEP 8 using the Black library
        final_code = black.format_str(final_code, mode=black.Mode())

        return final_code



    def get_function_parameters(self, func: Callable) -> List:
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


    def generate_workflow(self, load_order: List, filename: str = 'generated_code_workflow.py', queue_size: int = 10) -> str:
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
        import_statements, executed_variables, loader_code, code = set(['NODE_CLASS_MAPPINGS']), {}, [], []
        # This dictionary will store the names of the objects that we have already initialized
        initialized_objects = {}

        custom_nodes = False
        # Loop over each dictionary in the load order list
        for idx, data, is_loader in load_order:

            # Generate class definition and inputs from the data
            inputs, class_type = data['inputs'], data['class_type']
            class_def = NODE_CLASS_MAPPINGS[class_type]()

            # If the class hasn't been initialized yet, initialize it and generate the import statements
            if class_type not in initialized_objects:
                # No need to use preview image nodes since we are executing the script in a terminal
                if class_type == 'PreviewImage':
                    continue

                class_type, import_statement, class_code = self.get_class_info(class_type)
                initialized_objects[class_type] = class_type.lower()
                if class_type in self.BASE_NODE_CLASS_MAPPINGS.keys():
                    import_statements.add(import_statement)
                if class_type not in self.BASE_NODE_CLASS_MAPPINGS.keys():
                    custom_nodes = True
                loader_code.append(class_code)

            # Get all possible parameters for class_def
            class_def_params = self.get_function_parameters(getattr(class_def, class_def.FUNCTION))

            # Remove any keyword arguments from **inputs if they are not in class_def_params
            inputs = {key: value for key, value in inputs.items() if key in class_def_params}

            # Create executed variable and generate code
            executed_variables[idx] = f'{class_type.lower()}_{idx}'
            inputs = self.update_inputs(inputs, executed_variables)

            if is_loader:
                loader_code.append(self.create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_loader, **inputs))
            else:
                code.append(self.create_function_call_code(initialized_objects[class_type], class_def.FUNCTION, executed_variables[idx], is_loader, **inputs))

        # Generate final code by combining imports and code, and wrap them in a main function
        final_code = self.assemble_python_code(import_statements, loader_code, code, queue_size, custom_nodes)

        # Save the code to a .py file
        write_code_to_file(filename, final_code)

        return final_code


if __name__ == '__main__':
    input = 'workflow_api_serge.json'
    queue_size = 10
    ComfyUItoPython(input=input, queue_size=queue_size)
