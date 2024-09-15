# Music Tagging Parallel Training

This repository contains an example of distributed training for music tagging using the `torch.nn.DataParallel` framework. It demonstrates how to set up single-machine, multi-GPU parallel training.

## Setup Instructions

Please follow the steps below to set up and run the training process:

1. Clone the repository:

    ```bash
    git clone git@github.com:HarlandZZC/music_tagging_parallel.git
    cd music_tagging_parallel
    ```

2. Set up the environment:

    ```bash
    conda env create -f music_tagging_env.yaml
    ```

    If some packages cannot be installed through the YAML file, please download them manually.

3. Start training by running:

   ```bash
   python train.py
   ```

4. To evaluate the training results, run:

   ```bash
   python test.py
   ```
