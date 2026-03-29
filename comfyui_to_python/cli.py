from argparse import ArgumentParser

DEFAULT_INPUT_FILE = "workflow_api.json"
DEFAULT_OUTPUT_FILE = "workflow_api.py"
DEFAULT_QUEUE_SIZE = 10


def build_argument_parser() -> ArgumentParser:
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
    return parser


def main() -> None:
    from . import run

    parser = build_argument_parser()
    pargs = parser.parse_args()
    run(**vars(pargs))
    print("Done.")
