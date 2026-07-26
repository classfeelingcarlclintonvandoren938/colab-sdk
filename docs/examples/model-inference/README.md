# Model Inference Example

> Running inference with a simple model on Colab.

## Usage

```bash
python main.py
```

## What it does

1. Creates an App with a T4 GPU
2. Registers a `predict()` function that runs a linear model on the GPU
3. Passes a sample input vector as a `.remote()` argument
4. Returns the predicted class and confidence score
