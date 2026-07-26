# PyTorch Training Example

> Training a simple model on Colab GPU using the SDK.

## Usage

```bash
python main.py
```

## What it does

1. Creates an App with a T4 GPU
2. Registers a `train()` function that trains a linear model with PyTorch
3. Uploads a config file and injects a WandB API key via `app.secret()`
4. Calls `train.remote(epochs=10)` to execute on the Colab VM
5. Streams epoch logs in real-time
6. Downloads the trained checkpoint via `app.download()`
7. Returns the final loss as a JSON result
