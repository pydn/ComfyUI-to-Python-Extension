import copy
import inspect
import json
import keyword
import os
import random
import sys
import re
import traceback
from typing import Dict, List, Any, Callable, Tuple, TextIO, Mapping
from argparse import ArgumentParser

try:
    import black
except ImportError:
    class _BlackMode:
        pass

    class _BlackFallback:
        Mode = _BlackMode

        @staticmethod
        def format_str(code: str, mode: Any = None) -> str:
            return code

    black = _BlackFallback()

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfyui_to_python_utils import (
    import_custom_nodes,
    find_path,
    find_comfyui_root,
    normalize_path,
    add_comfyui_directory_to_sys_path,
    add_extra_model_paths,
    get_value_at_index,
)

try:
    add_comfyui_directory_to_sys_path()
    from nodes import NODE_CLASS_MAPPINGS
except Exception:
    NODE_CLASS_MAPPINGS = {}


DEFAULT_INPUT_FILE = "workflow_api.json"
DEFAULT_OUTPUT_FILE = "workflow_api.py"
DEFAULT_QUEUE_SIZE = 10


class ExportStageError(Exception):
    """Structured export failure that can be surfaced to the ComfyUI route."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        node_id: str | None = None,
        class_type: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.node_id = node_id
        self.class_type = class_type
        self.details = dict(details or {})

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "error": self.message,
            "stage": self.stage,
            "node_id": self.node_id,
            "class_type": self.class_type,
        }
        payload.update(self.details)
        return {key: value for key, value in payload.items() if value is not None}


class ExportResult:
    """Container for the generated code and any export diagnostics."""

    def __init__(self, code: str, diagnostics: List[Dict[str, Any]] | None = None):
        self.code = code
        self.diagnostics = diagnostics or []


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
            class_type = self.data[key]["class_type"]
            if class_type not in self.node_class_mappings:
                raise ExportStageError(
                    "Unsupported node class. Make sure the custom node is installed and loaded in ComfyUI.",
                    stage="resolve-node",
                    node_id=key,
                    class_type=class_type,
                )

            class_def = self.node_class_mappings[class_type]()
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
            set(["NODE_CLASS_MAPPINGS"]),
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
            if class_type not in self.node_class_mappings:
                raise ExportStageError(
                    "Unsupported node class. Make sure the custom node is installed and loaded in ComfyUI.",
                    stage="resolve-node",
                    node_id=idx,
                    class_type=class_type,
                )

            input_types = self.node_class_mappings[class_type].INPUT_TYPES()
            class_def = self.node_class_mappings[class_type]()

            # If required inputs are not present, fail with a structured error so the route can surface it.
            missing_required = []
            if "required" in input_types.keys():
                for required in input_types["required"]:
                    if required not in inputs.keys():
                        missing_required.append(required)
            if missing_required:
                raise ExportStageError(
                    "Workflow node is missing required inputs for export.",
                    stage="normalize-inputs",
                    node_id=idx,
                    class_type=class_type,
                    details={"missing_inputs": missing_required},
                )

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
                    import_statements.add(import_statement)
                if class_type not in self.base_node_class_mappings.keys():
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
            elif class_def_params is not None:
                if "unique_id" in class_def_params:
                    inputs["unique_id"] = random.randint(1, 2**64)

            # Create executed variable and generate code
            executed_variables[idx] = f"{self.clean_variable_name(class_type)}_{idx}"
            inputs = self.update_inputs(inputs, executed_variables)

            if is_special_function:
                special_functions_code.append(
                    self.create_function_call_code(
                        initialized_objects[class_type],
                        class_def.FUNCTION,
                        executed_variables[idx],
                        is_special_function,
                        inputs,
                    )
                )
            else:
                code.append(
                    self.create_function_call_code(
                        initialized_objects[class_type],
                        class_def.FUNCTION,
                        executed_variables[idx],
                        is_special_function,
                        inputs,
                    )
                )

        # Generate final code by combining imports and code, and wrap them in a main function
        final_code = self.assemble_python_code(
            import_statements, special_functions_code, code, queue_size, custom_nodes
        )

        return final_code

    def create_function_call_code(
        self,
        obj_name: str,
        func: str,
        variable_name: str,
        is_special_function: bool,
        inputs: Dict[str, Any],
    ) -> str:
        """Generate Python code for a function call.

        Args:
            obj_name (str): The name of the initialized object.
            func (str): The function to be called.
            variable_name (str): The name of the variable that the function result should be assigned to.
            is_special_function (bool): Determines the code indentation.
            inputs (Dict[str, Any]): The input values to pass to the function.

        Returns:
            str: The generated Python code.
        """
        args = ", ".join(self.format_arg(key, value) for key, value in inputs.items())

        # Generate the Python code
        code = f"{variable_name} = {obj_name}.{func}({args})\n"

        # If the code contains dependencies and is not a loader or encoder, indent the code because it will be placed inside
        # of a for loop
        if not is_special_function:
            code = f"\t{code}"

        return code

    def format_arg(self, key: str, value: Any) -> str:
        """Formats arguments based on key and value.

        Args:
            key (str): Argument key.
            value (any): Argument value.

        Returns:
            str: Formatted argument as a string.
        """
        rendered_value = self.render_value(key, value)
        if self.is_safe_kwarg(key):
            return f"{key}={rendered_value}"
        return f"**{{{json.dumps(key)}: {rendered_value}}}"

    def render_value(self, key: str, value: Any) -> str:
        """Render a value into a Python-safe source expression."""
        if key == "noise_seed" or key == "seed":
            return "random.randint(1, 2**64)"
        elif isinstance(value, str):
            return json.dumps(value)
        elif isinstance(value, dict) and "variable_name" in value:
            return value["variable_name"]
        return repr(value)

    def assemble_python_code(
        self,
        import_statements: set,
        speical_functions_code: List[str],
        code: List[str],
        queue_size: int,
        custom_nodes=False,
    ) -> str:
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
        for func in [
            get_value_at_index,
            normalize_path,
            find_path,
            find_comfyui_root,
            add_comfyui_directory_to_sys_path,
            add_extra_model_paths,
        ]:
            func_strings.append(f"\n{inspect.getsource(func)}")
        # Define static import statements required for the script
        static_imports = (
            [
                "import os",
                "import random",
                "import sys",
                "from typing import Sequence, Mapping, Any, Union",
                "import torch",
            ]
            + func_strings
            + ["\n\nadd_comfyui_directory_to_sys_path()\nadd_extra_model_paths()\n"]
        )
        # Check if custom nodes should be included
        if custom_nodes:
            static_imports.append(f"\n{inspect.getsource(import_custom_nodes)}\n")
            custom_nodes = "import_custom_nodes()\n\t"
        else:
            custom_nodes = ""
        # Create import statements for node classes
        imports_code = [
            f"from nodes import {', '.join([class_name for class_name in import_statements])}"
        ]
        # Assemble the main function code, including custom nodes if applicable
        main_function_code = (
            "def main():\n\t"
            + f"{custom_nodes}with torch.inference_mode():\n\t\t"
            + "\n\t\t".join(speical_functions_code)
            + f"\n\n\t\tfor q in range({queue_size}):\n\t\t"
            + ("\n\t\t".join(code) if code else "\tpass")
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
            class_code = f"{variable_name} = {class_type.strip()}()"
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
        clean_name = re.sub(r"[^a-z0-9_]", "", clean_name)

        # Ensure that it doesn't start with a number or collapse to an invalid identifier
        if not clean_name:
            clean_name = "node"
        if clean_name[0].isdigit():
            clean_name = "_" + clean_name
        if keyword.iskeyword(clean_name):
            clean_name = f"{clean_name}_node"

        return clean_name

    @staticmethod
    def is_safe_kwarg(key: str) -> bool:
        """True when a workflow input key can be emitted as a direct Python keyword argument."""
        return key.isidentifier() and not keyword.iskeyword(key)

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
            node_class_mappings (Dict): Mappings of node classes. Defaults to NODE_CLASS_MAPPINGS.
            needs_init_custom_nodes (bool): Whether to initialize custom nodes. Defaults to False.
        """
        if input_file and workflow:
            raise ValueError("Can't provide both input_file and workflow")
        elif not input_file and not workflow:
            raise ValueError("Needs input_file or workflow")

        if not output_file:
            raise ValueError("Needs output_file")

        self.workflow = workflow
        self.input_file = input_file
        self.output_file = output_file
        self.queue_size = queue_size
        self.node_class_mappings = (
            dict(node_class_mappings) if node_class_mappings is not None else dict(NODE_CLASS_MAPPINGS)
        )
        self.needs_init_custom_nodes = needs_init_custom_nodes

        self.base_node_class_mappings = copy.deepcopy(self.node_class_mappings)
        self.result = self.execute()

    def execute(self):
        """Execute the main workflow to generate Python code.

        Returns:
            ExportResult: Generated code and diagnostics.
        """
        # Step 1: Import all custom nodes if we need to
        if self.needs_init_custom_nodes:
            built_in_nodes = copy.deepcopy(self.base_node_class_mappings)
            import_custom_nodes()
            try:
                from nodes import NODE_CLASS_MAPPINGS as live_node_mappings

                self.node_class_mappings = dict(live_node_mappings)
                self.base_node_class_mappings = built_in_nodes
            except Exception:
                pass
        else:
            # If they're already imported, we don't know which nodes are custom nodes, so treat them all as NODE_CLASS_MAPPINGS lookups
            self.base_node_class_mappings = {}

        # Step 2: Read JSON data from the input file
        if self.input_file:
            data = FileHandler.read_json_file(self.input_file)
        else:
            data = json.loads(self.workflow)

        # Step 3: Determine the load order
        load_order_determiner = LoadOrderDeterminer(data, self.node_class_mappings)
        load_order = load_order_determiner.determine_load_order()

        # Step 4: Generate the workflow code
        code_generator = CodeGenerator(
            self.node_class_mappings, self.base_node_class_mappings
        )
        generated_code = code_generator.generate_workflow(
            load_order, queue_size=self.queue_size
        )

        # Step 5: Write the generated code to a file
        FileHandler.write_code_to_file(self.output_file, generated_code)

        return ExportResult(code=generated_code)


def export_workflow(
    *,
    workflow: str = "",
    input_file: str = "",
    output_file: str | TextIO,
    queue_size: int = 1,
    node_class_mappings: Dict | None = None,
    needs_init_custom_nodes: bool = False,
) -> ExportResult:
    """Generate Python code from a workflow string or file and return the result."""
    return ComfyUItoPython(
        workflow=workflow,
        input_file=input_file,
        output_file=output_file,
        queue_size=queue_size,
        node_class_mappings=node_class_mappings,
        needs_init_custom_nodes=needs_init_custom_nodes,
    ).result


def format_export_exception(exc: Exception) -> Dict[str, Any]:
    """Format exporter exceptions into a stable payload for the route/UI."""
    if isinstance(exc, ExportStageError):
        return exc.to_payload()

    return {
        "error": str(exc),
        "stage": "unexpected",
        "traceback": traceback.format_exc(),
    }


def run(
    input_file: str = DEFAULT_INPUT_FILE,
    output_file: str = DEFAULT_OUTPUT_FILE,
    queue_size: int = DEFAULT_QUEUE_SIZE,
) -> None:
    """Generate Python code from a ComfyUI workflow_api.json file.

    Args:
        input_file (str): Path to the input JSON file. Defaults to "workflow_api.json".
        output_file (str): Path to the output Python file.
            Defaults to "workflow_api.py".
        queue_size (int): The number of times a workflow will be executed by the script.
            Defaults to 1.

    Returns:
        None
    """
    export_workflow(
        input_file=input_file,
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
    pargs = parser.parse_args()
    try:
        run(**vars(pargs))
        print("Done.")
    except Exception as exc:
        print(json.dumps(format_export_exception(exc), indent=2))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    """Run the main function."""
    main()
