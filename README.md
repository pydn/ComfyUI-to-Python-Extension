**Status: Fork in development**. It works on my machine. It might not on yours.
Let me know of any major issues by submitting an Issue.
I plan to do some fresh install testing when I have time.

## ComfyUI-to-Python-Extension (SaveAsScript version)

This is a fork maintained by Anthony Maranto of the original [ComfyUI-To-Python-Extension](https://github.com/pydn/ComfyUI-to-Python-Extension) by Peyton DeNiro. It provides a more robust command-line interface and the ability to export your current workflow as a script directly from the ComfyUI web interface.

### Usage (Web)

Upon installation, there will be a button labeled "Save as Script" on the interface, pictured below:

![A button that exports the current script on the ComfyUI](images/save_as_script.png)

Click that button and enter your preferred name for the downloaded script (extension added automatically), and your file will be downloaded.

Note that if you use the script this way, you do **not** need to enable developer mode. You *will* if you use the CLI (to get the API JSON).

### Usage (CLI)

Navigating to the extension directory, you can also use the basic CLI included in the script to save your script without changing the Python file.

```bash
usage: comfyui_to_python.py [-h] [--output OUTPUT] [--queue-size QUEUE_SIZE] [--yes] workflow

Converts a ComfyUI-style workflow.json file to a Python file. Must have been exported with API calls

positional arguments:
  workflow              The workflow.json file to convert

options:
  -h, --help            show this help message and exit
  --output OUTPUT, -o OUTPUT
                        The output file (defaults to [input file].py)
  --queue-size QUEUE_SIZE, -q QUEUE_SIZE
                        The queue size per run
  --yes, --overwrite, -y
                        Overwrite the output file if it exists
```

### Other Changes

I also fixed what seemed to be a minor bug with exporting certain Crystools nodes, possibly due to their unusual name.

### Improvement TODO

Disable export of invalid nodes (ones for which required args are not satisfied) and log a warning to the console.

## Description of ComfyUI-to-Python-Extension (usage altered)

The `ComfyUI-to-Python-Extension` is a powerful tool that translates [ComfyUI](https://github.com/comfyanonymous/ComfyUI) workflows into executable Python code. Designed to bridge the gap between ComfyUI's visual interface and Python's programming environment, this script facilitates the seamless transition from design to code execution. Whether you're a data scientist, a software developer, or an AI enthusiast, this tool streamlines the process of implementing ComfyUI workflows in Python.

**Convert this:**

![SDXL UI Example](images/SDXL-UI-Example.jpg)


**To this:**

```
import random
import torch
import sys

sys.path.append("../")
from nodes import (
    VAEDecode,
    KSamplerAdvanced,
    EmptyLatentImage,
    SaveImage,
    CheckpointLoaderSimple,
    CLIPTextEncode,
)


def main():
    with torch.inference_mode():
        checkpointloadersimple = CheckpointLoaderSimple()
        checkpointloadersimple_4 = checkpointloadersimple.load_checkpoint(
            ckpt_name="sd_xl_base_1.0.safetensors"
        )

        emptylatentimage = EmptyLatentImage()
        emptylatentimage_5 = emptylatentimage.generate(
            width=1024, height=1024, batch_size=1
        )

        cliptextencode = CLIPTextEncode()
        cliptextencode_6 = cliptextencode.encode(
            text="evening sunset scenery blue sky nature, glass bottle with a galaxy in it",
            clip=checkpointloadersimple_4[1],
        )

        cliptextencode_7 = cliptextencode.encode(
            text="text, watermark", clip=checkpointloadersimple_4[1]
        )

        checkpointloadersimple_12 = checkpointloadersimple.load_checkpoint(
            ckpt_name="sd_xl_refiner_1.0.safetensors"
        )

        cliptextencode_15 = cliptextencode.encode(
            text="evening sunset scenery blue sky nature, glass bottle with a galaxy in it",
            clip=checkpointloadersimple_12[1],
        )

        cliptextencode_16 = cliptextencode.encode(
            text="text, watermark", clip=checkpointloadersimple_12[1]
        )

        ksampleradvanced = KSamplerAdvanced()
        vaedecode = VAEDecode()
        saveimage = SaveImage()

        for q in range(10):
            ksampleradvanced_10 = ksampleradvanced.sample(
                add_noise="enable",
                noise_seed=random.randint(1, 2**64),
                steps=25,
                cfg=8,
                sampler_name="euler",
                scheduler="normal",
                start_at_step=0,
                end_at_step=20,
                return_with_leftover_noise="enable",
                model=checkpointloadersimple_4[0],
                positive=cliptextencode_6[0],
                negative=cliptextencode_7[0],
                latent_image=emptylatentimage_5[0],
            )

            ksampleradvanced_11 = ksampleradvanced.sample(
                add_noise="disable",
                noise_seed=random.randint(1, 2**64),
                steps=25,
                cfg=8,
                sampler_name="euler",
                scheduler="normal",
                start_at_step=20,
                end_at_step=10000,
                return_with_leftover_noise="disable",
                model=checkpointloadersimple_12[0],
                positive=cliptextencode_15[0],
                negative=cliptextencode_16[0],
                latent_image=ksampleradvanced_10[0],
            )

            vaedecode_17 = vaedecode.decode(
                samples=ksampleradvanced_11[0], vae=checkpointloadersimple_12[2]
            )

            saveimage_19 = saveimage.save_images(
                filename_prefix="ComfyUI", images=vaedecode_17[0]
            )


if __name__ == "__main__":
    main()
```
## Potential Use Cases
- Streamlining the process for creating a lean app or pipeline deployment that uses a ComfyUI workflow
- Creating programmatic experiments for various prompt/parameter values
- Creating large queues for image generation (For example, you could adjust the script to generate 1000 images without clicking ctrl+enter 1000 times)
- Easily expanding or iterating on your architecture in Python once a foundational workflow is in place in the GUI

## V1.0.0 Release Notes
- **Use all the custom nodes!**
    - Custom nodes are now supported. If you run into any issues with code execution, first ensure that the each node works as expected in the GUI. If it works in the GUI, but not in the generated script, please submit an issue.


## Usage


1. Install the custom_node (via git cloning or the Manager)

2. Click the button in the web UI OR run the CLI

3. Move the created .py file to your `ComfyUI` folder

4. Run the generated script:
