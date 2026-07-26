"""
Model Inference — Colab Client example.

Runs a simple inference task on Colab GPU.

Usage:
    python main.py
"""

from colab import App

app = App(gpu="T4")


@app.function
def predict(input_data: list[float]) -> dict:
    import torch
    import torch.nn as nn

    model = nn.Linear(10, 3)

    with torch.no_grad():
        x = torch.tensor([input_data])
        output = model(x)
        predicted_class = int(output.argmax(dim=1).item())
        confidence = float(output.softmax(dim=1).max().item())

    return {
        "predicted_class": predicted_class,
        "confidence": confidence,
        "input_dimensions": len(input_data),
    }


if __name__ == "__main__":
    sample_input = [0.1] * 10
    result = predict.remote(sample_input)
    print(f"Prediction: class {result['predicted_class']} "
          f"(confidence: {result['confidence']:.2%})")
