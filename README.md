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

Requires Python 3.10+ and **Linux or macOS**. Windows users must use WSL2.

### Windows Setup (WSL2)

`google-colab-cli` requires Unix-only system modules and does not run on
native Windows. Use WSL2 instead:

1. **Install WSL2** (Admin PowerShell):
   ```powershell
   wsl --install -d Ubuntu
   ```

2. **Restart** your machine, then open the Ubuntu terminal.

3. **Install Python and Colab Client:**
   ```bash
   sudo apt update && sudo apt install python3 python3-pip -y
   pip install colab-client
   ```

4. **Authenticate with Google Colab:**
   ```bash
   colab auth login
   ```

All `colab` commands run inside WSL2. Your project files on the Windows
filesystem are accessible from WSL2 at `/mnt/c/`.

## License

MIT
