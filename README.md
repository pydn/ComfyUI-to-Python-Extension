## ComfyUI-to-Python-Extension

The `ComfyUI-to-Python-Extension` is a powerful tool that translates ComfyUI workflows into executable Python code. Designed to bridge the gap between ComfyUI's visual interface and Python's programming environment, this script facilitates the seamless transition from design to code execution. Whether you're a data scientist, a software developer, or an AI enthusiast, this tool streamlines the process of implementing ComfyUI workflows in Python. The output makes it easy to queue a large amount of images for generation and provides a base script to easily modify for experimination.

**Convert this:**

![SDXL UI Example](images/SDXL-UI-Example.jpg)


**To this:**

```
import random
import sys

sys.path.append("../")
from nodes import (
    KSamplerAdvanced,
    EmptyLatentImage,
    VAEDecodeTiled,
    SaveImage,
    CLIPTextEncode,
    CheckpointLoaderSimple,
)


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


1. Navigate to your `ComfyUI` directory

2. Clone this repo
    ```bash
    git clone https://github.com/pydn/ComfyUI-to-Python-Extension.git
    ```

    After cloning the repo, your `ComfyUI` directory should look like this:
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

3. Navigate to the `ComfyUI-to-Python-Extension` folder and install requirements
    ```bash
    pip install -r requirements.txt
    ```

4. Launch ComfyUI, click the gear icon over `Queue Prompt`, then check `Enable Dev mode Options`. **THE SCRIPT WILL NOT WORK IF YOU DO NOT ENABLE THIS OPTION!**

![Enable Dev Mode Options](images/dev_mode_options.jpg)

5. Load up your favorite workflows, then click the newly enabled `Save (API Format)` button under Queue Prompt

6. Move the downloaded .json workflow file to your `ComfyUI/ComfyUI-to-Python-Extension` folder

7. If needed, update the `input` variable at the bottom of `comfyui_to_python.py` to match the name of your .json workflow file. By default, the script will look for a file called `workflow_api.json`. You can also update the `queue_size` variable to your desired number of images that you want to generate in a single script execution. By default, the scripts will generate 10 images.

8. Run the script:
   ```bash
   python comfyui_to_python.py
   ```

9. After running `comfyui_to_python.py`, a new .py file will be created in the current working directory that contains the same name as the `input` variable. If you made no changes, look for `workflow_api.py`.

10. Now you can execute the newly created .py file to generate images without launching a server.