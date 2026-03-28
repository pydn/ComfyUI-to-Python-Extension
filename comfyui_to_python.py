import copy
import glob
import inspect
import json
import keyword
import os
import random
import sys
import re
from typing import Dict, List, Any, Callable, Tuple, TextIO
from argparse import ArgumentParser

import black

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfyui_to_python_utils import (
    import_custom_nodes,
    find_path,
    get_comfyui_path,
    add_comfyui_directory_to_sys_path,
    add_extra_model_paths,
    get_value_at_index,
)


DEFAULT_INPUT_FILE = "workflow_api.json"
DEFAULT_OUTPUT_FILE = "workflow_api.py"
DEFAULT_QUEUE_SIZE = 10


def get_node_class_mappings() -> Dict:
    """Load ComfyUI node mappings on demand.

    Tests that inject explicit node mappings should not need a full ComfyUI runtime
    just to import this module.
    """
    add_comfyui_directory_to_sys_path()
    from nodes import NODE_CLASS_MAPPINGS

    return NODE_CLASS_MAPPINGS


class FileHandler:
    """Handles reading and writing files.

    This class provides methods to read JSON data from an input file and write code to an output file.
    """

    @staticmethod
    def read_json_file(file_path: str | TextIO, encoding: str = "utf-8") -> dict:
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

        if hasattr(file_path, "read"):
            return json.load(file_path)
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data

    @staticmethod
    def write_code_to_file(file_path: str | TextIO, code: str) -> None:
        """Write the specified code to a Python file.

        Args:
            file_path (str): The path to the Python file.
            code (str): The code to write to the file.

        Returns:
            None
        """
        if isinstance(file_path, str):
            # Extract directory from the filename
            directory = os.path.dirname(file_path)

            # If the directory does not exist, create it
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            # Save the code to a .py file
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(code)
        else:
            file_path.write(code)


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
        inputs = self.data[key]["inputs"]
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
            class_def = self.node_class_mappings[self.data[key]["class_type"]]()
            # Check if the class is a loader class or meets specific conditions.
            if (
                class_def.CATEGORY == "loaders"
                or class_def.FUNCTION in ["encode"]
                or not any(
                    isinstance(val, list) for val in self.data[key]["inputs"].values()
                )
            ):
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

    def generate_workflow(
        self,
        load_order: List,
        workflow_data: Dict,
        metadata_workflow_data: Dict | None = None,
        queue_size: int = 10,
    ) -> str:
        """Generate the execution code based on the load order.

        Args:
            load_order (List): A list of tuples representing the load order.
            queue_size (int): The number of photos that will be created by the script.

        Returns:
            str: Generated execution code as a string.
        """
        # Create the necessary data structures to hold imports and generated code
        import_statements, executed_variables, special_functions_code, code = (
            {"nodes": {"NODE_CLASS_MAPPINGS"}},
            {},
            [],
            [],
        )
        # This dictionary will store the names of the objects that we have already initialized
        initialized_objects = {}

        custom_nodes = False
        # Loop over each dictionary in the load order list
        for idx, data, is_special_function in load_order:
            # Generate class definition and inputs from the data
            inputs, class_type = data["inputs"], data["class_type"]
            input_types = self.node_class_mappings[class_type].INPUT_TYPES()
            class_def = self.node_class_mappings[class_type]()

            # If required inputs are not present, skip the node as it will break the code if passed through to the script
            missing_required_variable = False
            if "required" in input_types.keys():
                for required in input_types["required"]:
                    if required not in inputs.keys():
                        missing_required_variable = True
            if missing_required_variable:
                continue

            # If the class hasn't been initialized yet, initialize it and generate the import statements
            if class_type not in initialized_objects:
                # No need to use preview image nodes since we are executing the script in a terminal
                if class_type == "PreviewImage":
                    continue

                class_type, import_statement, class_code = self.get_class_info(
                    class_type
                )
                initialized_objects[class_type] = self.clean_variable_name(class_type)
                if class_type in self.base_node_class_mappings.keys():
                    module_name, import_name = import_statement
                    import_statements.setdefault(module_name, set()).add(import_name)
                if 'NODE_CLASS_MAPPINGS["' in class_code:
                    custom_nodes = True
                special_functions_code.append(class_code)

            # Get all possible parameters for class_def
            class_def_params = self.get_function_parameters(
                getattr(class_def, class_def.FUNCTION)
            )
            no_params = class_def_params is None

            # Remove any keyword arguments from **inputs if they are not in class_def_params
            inputs = {
                key: value
                for key, value in inputs.items()
                if no_params or key in class_def_params
            }
            # Deal with hidden variables
            if (
                "hidden" in input_types.keys()
                and "unique_id" in input_types["hidden"].keys()
            ):
                inputs["unique_id"] = random.randint(1, 2**64)
            if "hidden" in input_types.keys():
                if "prompt" in input_types["hidden"].keys():
                    inputs["prompt"] = {"variable_name": "prompt"}
                if "extra_pnginfo" in input_types["hidden"].keys():
                    inputs["extra_pnginfo"] = {"variable_name": "extra_pnginfo"}
            elif class_def_params is not None:
                if "unique_id" in class_def_params:
                    inputs["unique_id"] = random.randint(1, 2**64)

            # Create executed variable and generate code
            executed_variables[idx] = (
                f"{self.clean_variable_name(class_type)}_"
                f"{self.clean_variable_name(str(idx))}"
            )
            inputs = self.update_inputs(inputs, executed_variables)

            if is_special_function:
                special_functions_code.append(
                    self.create_function_call_code(
                        initialized_objects[class_type],
                        class_def.FUNCTION,
                        executed_variables[idx],
                        is_special_function,
                        **inputs,
                    )
                )
            else:
                code.append(
                    self.create_function_call_code(
                        initialized_objects[class_type],
                        class_def.FUNCTION,
                        executed_variables[idx],
                        is_special_function,
                        **inputs,
                    )
                )

        # Generate final code by combining imports and code, and wrap them in a main function
        final_code = self.assemble_python_code(
            import_statements,
            special_functions_code,
            code,
            workflow_data,
            metadata_workflow_data or workflow_data,
            queue_size,
            custom_nodes,
        )

        return final_code

    def create_function_call_code(
        self,
        obj_name: str,
        func: str,
        variable_name: str,
        is_special_function: bool,
        **kwargs,
    ) -> str:
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
        args = ", ".join(self.format_arg(key, value) for key, value in kwargs.items())

        # Generate the Python code
        code = f"{variable_name} = {obj_name}.{func}({args})\n"

        # If the code contains dependencies and is not a loader or encoder, indent the code because it will be placed inside
        # of a for loop
        if not is_special_function:
            code = f"\t{code}"

        return code

    def format_arg(self, key: str, value: any) -> str:
        """Formats arguments based on key and value.

        Args:
            key (str): Argument key.
            value (any): Argument value.

        Returns:
            str: Formatted argument as a string.
        """
        value_code = self.format_arg_value(key, value)
        if key.isidentifier() and not keyword.iskeyword(key):
            return f"{key}={value_code}"
        return f"**{{{json.dumps(key)}: {value_code}}}"

    @staticmethod
    def format_arg_value(key: str, value: any) -> str:
        """Formats an argument value as Python source."""
        if key == "noise_seed" or key == "seed":
            return "random.randint(1, 2**64)"
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, dict) and "variable_name" in value:
            return value["variable_name"]
        return repr(value)

    def assemble_python_code(
        self,
        import_statements: Dict[str, set],
        speical_functions_code: List[str],
        code: List[str],
        workflow_data: Dict,
        metadata_workflow_data: Dict,
        queue_size: int,
        custom_nodes=False,
    ) -> str:
        """Generates the final code string.

        Args:
            import_statements (Dict[str, set]): Import statements grouped by module.
            speical_functions_code (List[str]): A list of special functions code strings.
            code (List[str]): A list of code strings.
            workflow_data (Dict): The API workflow data used for runtime prompt execution.
            metadata_workflow_data (Dict): The workflow metadata to embed into saved outputs.
            queue_size (int): Number of photos that will be generated by the script.
            custom_nodes (bool): Whether to include custom nodes in the code.

        Returns:
            str: Generated final code as a string.
        """
        # Get the source code of the utils functions as a string
        func_strings = []
        for func in [
            get_value_at_index,
            get_comfyui_path,
            find_path,
            add_comfyui_directory_to_sys_path,
            add_extra_model_paths,
        ]:
            func_strings.append(f"\n{inspect.getsource(func)}")
        # Define static import statements required for the script
        static_imports = (
            [
                "import json",
                "import os",
                "import random",
                "import sys",
                "from typing import Sequence, Mapping, Any, Union",
                "import torch",
            ]
            + func_strings
            + [
                "\n\nadd_comfyui_directory_to_sys_path()\nadd_extra_model_paths()\n",
                f"workflow = json.loads({json.dumps(json.dumps(workflow_data))})",
                "prompt = json.loads(json.dumps(workflow))",
                (
                    "extra_pnginfo = "
                    '{"workflow": json.loads('
                    + json.dumps(json.dumps(metadata_workflow_data))
                    + ")}"
                ),
            ]
        )
        # Check if custom nodes should be included
        if custom_nodes:
            static_imports.append(f"\n{inspect.getsource(import_custom_nodes)}\n")
            custom_nodes = "import_custom_nodes()\n\t"
        else:
            custom_nodes = ""
        # Create import statements for node classes
        imports_code = []
        for module_name in sorted(import_statements.keys()):
            class_names = ", ".join(sorted(import_statements[module_name]))
            imports_code.append(f"from {module_name} import {class_names}")
        special_functions_body = "\n\t\t".join(speical_functions_code) or "pass"
        loop_body = "\n\t\t".join(code) or "\tpass"
        # Assemble the main function code, including custom nodes if applicable
        main_function_code = (
            "def main():\n\t"
            + f"{custom_nodes}with torch.inference_mode():\n\t\t"
            + special_functions_body
            + f"\n\n\t\tfor q in range({queue_size}):\n\t\t"
            + loop_body
        )
        # Concatenate all parts to form the final code
        final_code = "\n".join(
            static_imports
            + imports_code
            + ["", main_function_code, "", 'if __name__ == "__main__":', "\tmain()"]
        )
        # Format the final code according to PEP 8 using the Black library
        final_code = black.format_str(final_code, mode=black.Mode())

        return final_code

    def get_class_info(self, class_type: str) -> Tuple[str, Tuple[str, str], str]:
        """Generates and returns necessary information about class type.

        Args:
            class_type (str): Class type.

        Returns:
            Tuple[str, Tuple[str, str], str]: Updated class type, import statement and initialization code.
        """
        class_obj = self.base_node_class_mappings.get(class_type)
        module_name = "nodes"
        if class_obj is not None:
            module_name = class_obj.__module__
        variable_name = self.clean_variable_name(class_type)
        is_importable_module = bool(
            module_name
            and "/" not in module_name
            and "\\" not in module_name
            and all(part.isidentifier() for part in module_name.split("."))
        )
        if class_type in self.base_node_class_mappings.keys() and is_importable_module:
            import_statement = (module_name, class_type)
            class_code = f"{variable_name} = {class_type.strip()}()"
        else:
            import_statement = ("nodes", "NODE_CLASS_MAPPINGS")
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
        clean_name = re.sub(r"[^a-z0-9_]", "", clean_name)

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
        parameters = {
            name: param.default if param.default != param.empty else None
            for name, param in signature.parameters.items()
        }
        catch_all = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )
        return list(parameters.keys()) if not catch_all else None

    def update_inputs(self, inputs: Dict, executed_variables: Dict) -> Dict:
        """Update inputs based on the executed variables.

        Args:
            inputs (Dict): Inputs dictionary to update.
            executed_variables (Dict): Dictionary storing executed variable names.

        Returns:
            Dict: Updated inputs dictionary.
        """
        for key in inputs.keys():
            if (
                isinstance(inputs[key], list)
                and inputs[key][0] in executed_variables.keys()
            ):
                inputs[key] = {
                    "variable_name": f"get_value_at_index({executed_variables[inputs[key][0]]}, {inputs[key][1]})"
                }
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

    def __init__(
        self,
        workflow: str = "",
        frontend_workflow: str | Dict | None = None,
        input_file: str = "",
        output_file: str | TextIO = "",
        queue_size: int = 1,
        node_class_mappings: Dict | None = None,
        needs_init_custom_nodes: bool = False,
    ):
        """Initialize the ComfyUItoPython class with the given parameters. Exactly one of workflow or input_file must be specified.
        Args:
            workflow (str): The workflow's JSON.
            input_file (str): Path to the input JSON file.
            output_file (str | TextIO): Path to the output file or a file-like object.
            queue_size (int): The number of times a workflow will be executed by the script. Defaults to 1.
            node_class_mappings (Dict | None): Mappings of node classes. Defaults to the current
                ComfyUI NODE_CLASS_MAPPINGS when not provided.
            needs_init_custom_nodes (bool): Whether to initialize custom nodes. Defaults to False.
        """
        if input_file and workflow:
            raise ValueError("Can't provide both input_file and workflow")
        elif not input_file and not workflow:
            raise ValueError("Needs input_file or workflow")

        if not output_file:
            raise ValueError("Needs output_file")

        self.workflow = workflow
        self.frontend_workflow = frontend_workflow
        self.input_file = input_file
        self.output_file = output_file
        self.queue_size = queue_size
        self.node_class_mappings = (
            node_class_mappings
            if node_class_mappings is not None
            else get_node_class_mappings()
        )
        self.needs_init_custom_nodes = needs_init_custom_nodes

        self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)
        self.execute()

    def execute(self):
        """Execute the main workflow to generate Python code.

        Returns:
            None
        """
        # Step 1: Read JSON data from the input file
        if self.input_file:
            data = FileHandler.read_json_file(self.input_file)
        else:
            data = json.loads(self.workflow)

        frontend_workflow_data = None
        if self.frontend_workflow:
            if isinstance(self.frontend_workflow, str):
                frontend_workflow_data = json.loads(self.frontend_workflow)
            else:
                frontend_workflow_data = self.frontend_workflow

        # Step 2: Initialize extra/custom nodes when requested or when the workflow references
        # a node class that is not currently loaded in the runtime.
        missing_node_types = {
            node_data["class_type"]
            for node_data in data.values()
            if node_data["class_type"] not in self.node_class_mappings
        }
        if self.needs_init_custom_nodes or missing_node_types:
            import_custom_nodes()
            self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)

        # Step 3: Determine the load order
        load_order_determiner = LoadOrderDeterminer(data, self.node_class_mappings)
        load_order = load_order_determiner.determine_load_order()

        # Step 4: Generate the workflow code
        code_generator = CodeGenerator(
            self.node_class_mappings, self.base_node_class_mappings
        )
        generated_code = code_generator.generate_workflow(
            load_order,
            data,
            frontend_workflow_data,
            queue_size=self.queue_size,
        )

        # Step 5: Write the generated code to a file
        FileHandler.write_code_to_file(self.output_file, generated_code)

        print(f"Code successfully generated and written to {self.output_file}")


def run(
    input_file: str = DEFAULT_INPUT_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    queue_size: int = DEFAULT_QUEUE_SIZE,
    frontend_workflow_file: str = "",
) -> None:
    """Generate Python code from a ComfyUI workflow_api.json file.

    Args:
        input_file (str): Path to the input JSON file. Defaults to "workflow_api.json".
        output_file (str): Path to the output Python file.
            Defaults to "workflow_api.py".
        queue_size (int): The number of times a workflow will be executed by the script.
            Defaults to 1.
        frontend_workflow_file (str): Optional path to a full frontend workflow JSON file.
            When provided, generated images can preserve reimportable ComfyUI workflow metadata.

    Returns:
        None
    """
    ComfyUItoPython(
        input_file=input_file,
        frontend_workflow=(
            FileHandler.read_json_file(frontend_workflow_file)
            if frontend_workflow_file
            else None
        ),
        output_file=output_file,
        queue_size=queue_size,
        needs_init_custom_nodes=True,
    )


def main() -> None:
    """Main function to generate Python code from a ComfyUI workflow_api.json file."""
    parser = ArgumentParser(
        description="Generate Python    code from a ComfyUI workflow_api.json file."
    )
    parser.add_argument(
        "-f",
        "--input_file",
        type=str,
        help="path to the input JSON file",
        default=DEFAULT_INPUT_FILE,
    )
    parser.add_argument(
        "-o",
        "--output_file",
        type=str,
        help="path to the output Python file",
        default=DEFAULT_OUTPUT_FILE,
    )
    parser.add_argument(
        "-q",
        "--queue_size",
        type=int,
        help="number of times the workflow will be executed by default",
        default=DEFAULT_QUEUE_SIZE,
    )
    parser.add_argument(
        "--frontend_workflow_file",
        type=str,
        help="optional path to a full frontend workflow JSON file for reimportable PNG metadata",
        default="",
    )
    pargs = parser.parse_args()
    run(**vars(pargs))
    print("Done.")


if __name__ == "__main__":
    """Run the main function."""
    main()
