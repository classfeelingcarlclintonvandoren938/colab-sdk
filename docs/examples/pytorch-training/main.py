"""
PyTorch Training — Colab Client example.

Trains a simple linear model on Colab GPU.

Usage:
    python main.py
"""

from colab import App

app = App(gpu="T4")


@app.function
def train(epochs: int = 5) -> dict:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    model = nn.Linear(10, 1)
    optimizer = optim.SGD(model.parameters(), lr=0.01)
    loss_fn = nn.MSELoss()

    for epoch in range(epochs):
        x = torch.randn(32, 10)
        y = torch.randn(32, 1)

        optimizer.zero_grad()
        y_pred = model(x)
        loss = loss_fn(y_pred, y)
        loss.backward()
        optimizer.step()

        print(f"Epoch {epoch + 1}/{epochs} — Loss: {loss.item():.4f}")

    return {"status": "complete", "final_loss": loss.item()}


if __name__ == "__main__":
    # Upload config before training
    app.upload("config.yaml")

    # Set an API key as a secret
    app.secret("WANDB_API_KEY", "my-api-key")

    result = train.remote(epochs=10)
    print(f"Training complete: {result}")

    # Download the trained checkpoint
    app.download("/content/model.pt", "./checkpoint.pt")
