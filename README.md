<div align="center">

# Colab Client 🚀

**A Python SDK that turns Google Colab into a remote compute runtime.**

[![PyPI version](https://img.shields.io/badge/pypi-v0.1.0-blue.svg)](https://pypi.org/project/colab-client/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-green.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-126%20passing-brightgreen.svg)](docs/PROGRESS.md)
[![Google Colab](https://img.shields.io/badge/Google%20Colab-runtime-orange.svg)](https://colab.research.google.com/)

```python
from colab import App

app = App()

@app.function(gpu="T4")
def train(epochs: int) -> dict:
    import torch
    model = torch.nn.Linear(10, 1)
    return {"done": True, "epochs": epochs}

result = train.remote(epochs=10)
print(result)  # {'done': True, 'epochs': 10}
```

**[Install](#installation) · [Quick Start](#quick-start) · [API Reference](#api-reference) · [Architecture](docs/foundation/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md)**

</div>

---

## Table of Contents

- [Why Colab Client?](#why-colab-client)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Advanced Usage](#advanced-usage)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Comparison](#comparison)
- [FAQ](#faq)
- [Project Status](#project-status)
- [Contributing](#contributing)
- [License](#license)

---

## Why Colab Client?

Google Colab provides **free GPU compute** (T4, L4, A100) — but the developer experience is stuck in notebooks. You need to manually upload files, manage cells, and deal with a browser-based workflow. Modern cloud compute platforms like Modal and RunPod solve this, but they're paid.

**Colab Client bridges the gap.** It gives you the developer experience of modern compute platforms while leveraging Google's free GPU resources.

### Key Benefits

| | Without Colab Client | With Colab Client |
|---|---|---|
| **Workflow** | Write code in Jupyter notebooks | Write normal Python files |
| **File management** | Manual upload/download | Automatic dependency analysis |
| **GPU setup** | Runtime → Change runtime type → Save | `App(gpu="T4")` |
| **Code reuse** | Copy-paste between notebooks | Standard Python imports |
| **Cost** | Free (Google Colab) | Free (Google Colab) |

### Who Is This For?

- **AI/ML learners** who want GPU compute without paying for cloud services
- **Indie hackers** prototyping ML models on a budget
- **Students** working on research projects with limited resources
- **Open-source developers** who need GPU for testing and experimentation
- **Anyone** who finds Colab notebooks tedious but wants free GPUs

---

## Installation

### Prerequisites

- Python 3.10+
- **Linux or macOS** (Windows users: [WSL2](#windows-setup-wsl2))

### Install from PyPI

```bash
pip install colab-client
```

### Install from Source

```bash
git clone https://github.com/heyncth/colab-client.git
cd colab-client
pip install -e .
```

### Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### Windows Setup (WSL2)

`google-colab-cli` requires Unix system modules and **does not run on native Windows**. Use WSL2:

1. **Install WSL2** (run in PowerShell as Admin):
   ```powershell
   wsl --install -d Ubuntu
   ```

2. **Restart** your machine, then open the Ubuntu terminal.

3. **Install Python and the SDK:**
   ```bash
   sudo apt update && sudo apt install python3 python3-pip -y
   pip install colab-client
   ```

4. **Authenticate with Google Colab:**
   ```bash
   colab new -s test-session
   ```
   Follow the OAuth URL in your browser and paste the authorization code.

> **Tip:** If `colab` is not found after installation, create a `.env` file in your project root:
> ```bash
> COLAB_BIN_DIR=/home/user/.local/bin
> ```
> See [Session docs](docs/components/session/SPEC.md#env-support) for details.

---

## Quick Start

### 1. Create an App

```python
from colab import App

app = App()  # CPU session by default
```

For GPU:

```python
app = App(gpu="T4")  # T4, L4, A100, or H100
```

### 2. Register a Function

```python
@app.function
def hello() -> str:
    return "Hello from Colab!"
```

With GPU override and timeout:

```python
@app.function(gpu="A100", timeout=600)
def train(epochs: int, lr: float = 0.01) -> dict:
    import torch
    import time
    model = torch.nn.Linear(10, 1)
    time.sleep(1)  # simulate training
    return {"done": True, "epochs": epochs, "lr": lr}
```

### 3. Execute Remotely

```python
# First call takes ~20s (VM provisioning)
result = hello.remote()
print(result)  # "Hello from Colab!"

# Subsequent calls are ~2s (session reuse)
result = train.remote(epochs=5, lr=0.001)
print(result)  # {'done': True, 'epochs': 5, 'lr': 0.001}
```

### 4. Clean Up

```python
app.shutdown()  # Terminates the Colab VM
```

> See the [integration test](examples/integration_test.py) for a complete working example.

---

## API Reference

### `App` — Main Entry Point

```python
from colab import App

app = App(
    gpu=None,           # str | None: "T4", "L4", "A100", "H100", or None for CPU
    idle_timeout="30m", # str | None: "30m", "1h", etc.
    session_name=None,  # str | None: auto-generated if omitted
)
```

**Properties:**

| Property | Type | Description |
|---|---|---|
| `app.engine` | `ExecutionEngine` | The engine instance (useful for advanced use) |
| `app.session_name` | `str` | The Colab session name |
| `app.gpu` | `str \| None` | The GPU type |
| `app.secrets` | `dict[str, str]` | Read-only view of stored secrets |

### `@app.function` — Decorator

```python
# Bare decorator
@app.function
def my_func():
    ...

# With arguments
@app.function(gpu="T4", timeout=300)
def my_func():
    ...

# Non-decorator form (for pre-defined functions)
my_func = app.function(my_func)
```

### `RemoteFunction.remote()` — Execute

```python
result = my_func.remote(*args, debug=False, **kwargs)
```

| Parameter | Type | Description |
|---|---|---|
| `*args` | `tuple` | Positional arguments (must be JSON-serializable) |
| `debug` | `bool` | Print raw VM output to stderr |
| `**kwargs` | `dict` | Keyword arguments (must be JSON-serializable) |

> See [Function SPEC](docs/components/function/SPEC.md) for complete documentation.

### Lifecycle Methods

```python
app.login()               # Trigger authentication (optional, auto-triggered)
app.shutdown()            # Terminate the Colab VM
```

### File Transfer

```python
app.upload("model.pt")                             # Upload to /content/model.pt
app.upload("data.zip", "/content/data/data.zip")   # Upload to custom path
app.download("checkpoint.pt")                      # Download to ./checkpoint.pt
app.download("/content/logs.txt", "./logs.txt")     # Download to custom path
```

### Secrets

```python
app.secret("HF_TOKEN", "hf_abc123")
app.secret("WANDB_API_KEY", "wandb_xyz")
```

Secrets are injected as environment variables on the Colab VM before your function executes.

> See [App SPEC](docs/components/app/SPEC.md) for complete documentation.

---

## Advanced Usage

### Debug Mode

When things go wrong, enable debug mode to see every raw line from the VM:

```python
result = train.remote(debug=True, epochs=5)
# [colab-raw] Traceback (most recent call last):
# [colab-raw]   ...
```

### Pre-Defined Functions (Avoiding SDK Import on VM)

For the VM to import your functions, they must be at **module level** (no SDK dependency):

```python
# ----- my_script.py -----
# These run on the VM — NO SDK imports allowed
def hello() -> str:
    return "Hello from Colab!"

def add(a: int, b: int) -> int:
    return a + b

# This runs locally only
def main():
    from colab import App
    app = App()
    hello_fn = app.function(hello)
    add_fn = app.function(add)
    print(hello_fn.remote())
    print(add_fn.remote(40, 2))
    app.shutdown()

if __name__ == "__main__":
    main()
```

> See the [integration test](examples/integration_test.py) for a complete example of this pattern.

### Using Requirements (External Packages)

The Analyzer automatically detects external packages:

```python
@app.function
def train():
    import torch       # → added to requirements
    import numpy as np # → added to requirements
    ...
```

Requirements are cached on the VM by hash — re-installation is skipped if the hash matches.

### GPU Selection

```python
# CPU session (free, fast startup)
app = App()

# GPU sessions (requires Colab Pro or pay-as-you-go)
app = App(gpu="T4")    # Entry-level GPU
app = App(gpu="L4")    # Mid-range GPU
app = App(gpu="A100")  # High-end GPU (Colab Pro+)
app = App(gpu="H100")  # Latest GPU (Colab Pro+)
```

---

## How It Works

```
Your Code → Analyzer (AST) → ExecutionManifest → Wrapper (base64 inline)
                                                      ↓
                                              Colab VM ← colab exec stdin
                                                      ↓
                                              Function executes → __LAZY_RESULT__
                                                      ↓
                                              Parse → Return to caller
```

1. **Validate** — Checks GPU type against known list
2. **Analyze** — Parses your function's AST to discover dependencies and requirements
3. **Build Wrapper** — Base64-encodes all source files into a self-contained Python script
4. **Ensure Session** — Creates Colab VM if needed (lazy, on first call)
5. **Install Requirements** — Installs packages if not cached by hash
6. **Execute** — Sends wrapper code via `colab exec` stdin
7. **Parse** — Streams stdout, detects `__LAZY_RESULT__` or `__LAZY_ERROR__` markers
8. **Return** — Deserializes JSON result to caller

> See [Architecture](docs/foundation/ARCHITECTURE.md) for the complete system design.

### The `__LAZY_*` Protocol

The Colab VM communicates results via structured stdout/stderr markers:

| Marker | Purpose |
|---|---|
| `__LAZY_RESULT__:{"status":"ok","value":42}` | Successful return value |
| `__LAZY_ERROR__:{"status":"error",...}` | Exception details with traceback |
| `__LAZY_LOG__:Training started` | Log messages forwarded in real-time |
| `__LAZY_PROGRESS__:50` | Progress updates (0-100) |

> See [Stdout Protocol](docs/protocols/stdout-protocol.md) for the full specification.

---

## Architecture

Colab Client consists of six components, each with a single responsibility:

| Component | Responsibility | Docs |
|---|---|---|
| **App** | SDK entry point, holds configuration | [SPEC](docs/components/app/SPEC.md) · [ADR](docs/components/app/ADR.md) |
| **RemoteFunction** | Function metadata, delegates `.remote()` | [SPEC](docs/components/function/SPEC.md) · [ADR](docs/components/function/ADR.md) |
| **ExecutionEngine** | Pipeline orchestrator, retry logic | [SPEC](docs/components/engine/SPEC.md) · [ADR](docs/components/engine/ADR.md) |
| **Analyzer** | AST-based import resolution | [SPEC](docs/components/analyzer/SPEC.md) · [ADR](docs/components/analyzer/ADR.md) |
| **Packager** | Deterministic tar.gz artifact builder | [SPEC](docs/components/packager/SPEC.md) · [ADR](docs/components/packager/ADR.md) |
| **ColabSession** | CLI wrapper for google-colab-cli | [SPEC](docs/components/session/SPEC.md) · [ADR](docs/components/session/ADR.md) |

### Key Design Decisions

- **Colab only** — No multi-provider abstraction. See [ADR-001](docs/foundation/ADR/001-colab-only.md)
- **Official CLI** — Uses google-colab-cli, no reverse engineering. See [ADR-002](docs/foundation/ADR/002-google-colab-cli.md)
- **Static analysis** — AST-based import resolution, no runtime execution. See [ADR-003](docs/foundation/ADR/003-static-analysis.md)
- **Fail fast** — Validate at decoration time, not runtime. See [ADR-004](docs/foundation/ADR/004-fail-fast.md)
- **Persistent session** — One App = one VM, lazy creation. See [ADR-006](docs/foundation/ADR/006-persistent-session.md)
- **Inline delivery** — Source files sent via base64, no upload needed. See [Session ADR](docs/components/session/ADR.md)

### Project Documentation

| Document | Description |
|---|---|
| [PRD](docs/foundation/PRD.md) | Product requirements, vision, and scope |
| [Architecture](docs/foundation/ARCHITECTURE.md) | System design, data flow, glossary |
| [Progress](docs/PROGRESS.md) | Session log, milestones, commit history |
| [Future Features](docs/future_implement.md) | Deferred features catalog (Tiers 1-3) |
| [CODING_STANDARDS.md](CODING_STANDARDS.md) | Python conventions, linting, testing |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [CONSTITUTION.md](CONSTITUTION.md) | Project laws and invariants |
| [AGENTS.md](AGENTS.md) | AI agent behavior rules |

---

## Comparison

### vs. Google Colab (Notebook)

| Feature | Colab Notebook | Colab Client |
|---|---|---|
| **Code editing** | Browser-based cells | Any IDE (VS Code, PyCharm, etc.) |
| **Version control** | Manual export/import | Standard Git workflow |
| **Dependencies** | `!pip install` in cells | Automatic from imports |
| **File transfer** | Manual upload/download | Automatic + `app.upload()`/`app.download()` |
| **Session reuse** | Manual reconnect | Automatic |

### vs. Modal, RunPod, Beam

| Feature | Modal (Paid) | RunPod (Paid) | Colab Client (Free) |
|---|---|---|---|
| **GPU cost** | Pay per second | Pay per hour | Free (Colab quota) |
| **GPU types** | A100, H100, L40S | A100, H100, RTX | T4, L4, A100 (Pro) |
| **Max session** | 24h (default) | Configurable | 24h (Colab limit) |
| **Stateful classes** | `@app.cls()` | N/A | Planned ([Tier 1](docs/future_implement.md)) |
| **`pip install`** | `modal` | Custom | `colab-client` |

---

## FAQ

### Is this free?

Yes! Colab Client uses Google Colab's free tier. GPU sessions may require Colab Pro or pay-as-you-go compute units (starting at ~$0.01/hour).

### Does this work on Windows?

Not natively — `google-colab-cli` requires Unix system modules. Use WSL2 (see [Windows Setup](#windows-setup-wsl2)).

### How fast is the first call?

~20-30 seconds for VM provisioning. Subsequent calls are ~1-2 seconds (session reuse).

### Can I use multiple GPUs?

Only one GPU per session, matching Colab's limits. You can create multiple `App` instances for multiple sessions.

### What if my Colab session dies?

The Engine automatically detects dead sessions and creates a new one (see [Engine SPEC](docs/components/engine/SPEC.md#retry-logic)).

### Are my secrets secure?

Secrets are stored in memory on your local machine and embedded into the wrapper code sent to the VM. They are not persisted to disk.

---

## Project Status

**MVP complete** — All core features are implemented and integration-tested against real Colab:

| Component | Status | Tests |
|---|---|---|
| App + RemoteFunction | ✅ | 21 tests |
| ExecutionEngine | ✅ | 21 tests |
| Analyzer | ✅ | 10 tests |
| Packager | ✅ | 8 tests |
| ColabSession | ✅ | 17 tests |
| Protocol Parser | ✅ | 23 tests |
| Integration Test | ✅ | Passed (real Colab) |
| **Total** | **✅** | **126 tests** |

### Upcoming Features

| Tier | Features |
|---|---|
| **1** | Stateful classes (`@app.cls()`), Non-blocking (`.spawn()`), Parallel (`.map()`), Persistent volumes |
| **2** | HTTP endpoints, Named secrets, Multiple sessions, Progress callbacks |
| **3** | Cache visualization, Model registry, Session snapshots |

See [Future Features](docs/future_implement.md) for the complete roadmap.

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development setup
- Coding standards (ruff, mypy, pytest)
- Pull request process
- Architecture decision records

### Quick Start for Contributors

```bash
git clone https://github.com/heyncth/colab-client.git
cd colab-client
pip install -e ".[dev]"
pytest tests/
```

---

## License

MIT © [Contributors](https://github.com/heyncth/colab-client/graphs/contributors)

---

<div align="center">

**Made for the free GPU community** ❤️

[GitHub](https://github.com/heyncth/colab-client) · [Issues](https://github.com/heyncth/colab-client/issues) · [Discussions](https://github.com/heyncth/colab-client/discussions)

</div>
