## Overview

The `ComfyUI-to-Python-Extension` is a powerful tool that translates ComfyUI workflow into executable Python code. Designed to bridge the gap between ComfyUI's visual interface and Python's programming environment, this script facilitates the seamless transition from design to code execution. Whether you're a data scientist, a software developer, or an AI enthusiast, this tool streamlines the process of implementing ComfyUI workflows in Python. The output makes it easy to queue a large amount of images for generation and provides a base script to easily modify for experimination.

**Convert this:**

![SDXL UI Example](images/SDXL-UI-Example.jpg)


**To this:**

```
import random
import sys

sys.path.append("../")
from nodes import KSamplerAdvanced
from nodes import EmptyLatentImage
from nodes import VAEDecodeTiled
from nodes import SaveImage
from nodes import CheckpointLoaderSimple
from nodes import CLIPTextEncode


def main():
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
    vaedecodetiled = VAEDecodeTiled()
    saveimage = SaveImage()

    for q in range(1, 10):
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

        vaedecodetiled_17 = vaedecodetiled.decode(
            samples=ksampleradvanced_11[0], vae=checkpointloadersimple_12[2]
        )

        saveimage_19 = saveimage.save_images(
            filename_prefix="ComfyUI", images=vaedecodetiled_17[0].detach()
        )


if __name__ == "__main__":
    main()
```

## Usage

1. **Clone this repo**
    ```bash
    git clone https://github.com/pydn/ComfyUI-to-Python-Extension.git
    ```

2. **Install requirements**
    ```bash
    pip install -r requirements.txt
    ```

3. **Copy files into ComfyUI**: Copy [`ComfyUI-to-Python-Extension/`](https://github.com/pydn/ComfyUI-to-Python-Extension/tree/main/ComfyUI-to-Python-Extension) into the parent folder of your cloned version of ComfyUI. 

    After copying `ComfyUI-to-Python-Extension/` your local `ComfyUI` directory should look like this:
    ```
    /comfy
    /comfy_extras
    /ComfyUI-to-Python-Extension
    /custom_nodes
    /input
    /models
    /output
    /script_examples
    /web
    .gitignore
    LICENSE
    README.md
    comfyui_screenshot.png
    cuda_mollac.py
    execution.py
    extra_model_paths.yaml.example
    folder_paths.py
    latent_preview.py
    main.py
    nodes.py
    requirements.txt
    server.py
    ```

4. **Navigate to the `ComfyUI-to-Python-Extension` folder in your local `ComfyUI` directory.**

5. **Run the Script**: Use the following command to run the script with a specific JSON file:

   ```bash
   python generate_python_code.py
   ```