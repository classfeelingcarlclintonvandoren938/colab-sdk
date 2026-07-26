# Colab Client

A Python SDK that turns Google Colab into a remote compute runtime.

Execute local Python functions remotely on Google Colab with a clean Python API.

```python
from colab import App

app = App()

@app.function(gpu="T4")
def train():
    import torch
    model = torch.nn.Linear(10, 1)
    return "Training complete"

result = train.remote()
print(result)
```

## Installation

```bash
pip install colab-client
```

Requires Python 3.10+.

## License

MIT
