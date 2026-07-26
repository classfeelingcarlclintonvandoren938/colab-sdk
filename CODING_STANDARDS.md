# Coding Standards — Colab Client

> Tech stack, code conventions, and patterns.

---

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.10+ |
| Package manager | `pip` (standard) or `uv` |
| Build system | `hatchling` (via `pyproject.toml`) |
| Testing | `pytest` |
| Linting | `ruff` |
| Type checking | `mypy` (strict mode) |
| Formatting | `ruff format` |
| CI | GitHub Actions |
| Pre-commit | `ruff check`, `ruff format --check`, `mypy`, `pytest` |

## Pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "colab-client"
dynamic = ["version"]
description = "A Python SDK that turns Google Colab into a remote compute runtime."
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
dependencies = [
    "google-colab-cli",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "ruff",
    "mypy",
]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.mypy]
strict = true
python_version = "3.10"
```

## Project Structure

```
src/colab/
    __init__.py         # Public API exports (App, RemoteFunction)
    _app.py             # App class (internal — accessed via App from __init__)
    _function.py        # RemoteFunction decorator
    _engine.py          # ExecutionEngine orchestrator
    _analyzer.py        # Static dependency analysis
    _packager.py        # Artifact packaging
    _session.py         # ColabSession (google-colab-cli wrapper)
    _manifest.py        # ExecutionManifest model
    _exceptions.py      # Custom exceptions
    _protocol.py        # Stdout protocol parsing

tests/
    test_analyzer.py
    test_packager.py
    test_session.py
    test_engine.py
    test_app.py
```

### Public vs Private

- `__init__.py` exports the public API only: `App`, `RemoteFunction`, and custom exception classes.
- All implementation modules are prefixed with `_` to signal they are private. Users should never `from colab._engine import ...`.
- The only allowed imports from outside the package are:
  ```python
  from colab import App           # Public
  from colab import RemoteFunction # Public (rarely needed directly)
  ```

## Python Conventions

### Imports

```python
# Standard library first
import ast
import hashlib
import subprocess
from pathlib import Path

# Local
from colab._manifest import ExecutionManifest
```

### Type Annotations

All public functions and methods must have type annotations:

```python
def analyze(function: RemoteFunction) -> ExecutionManifest:
    ...
```

Use `mypy --strict`. No `# type: ignore` without a comment explaining why.

### Error Handling

Use custom exceptions from `exceptions.py`:

```python
class AnalysisError(Exception): ...
class SessionError(Exception): ...
class SessionDeadError(Exception): ...
class SessionGpuMismatchError(Exception): ...
class AuthError(Exception): ...
class RemoteExecutionError(Exception): ...
class ProtocolError(Exception): ...
class ValidationError(Exception): ...
```

Raise specific exceptions. Never raise bare `Exception` or `RuntimeError`.

## Testing

- `pytest` with `unittest.mock` for mocking `subprocess` and `google-colab-cli` calls.
- Test files mirror the source structure: `tests/test_analyzer.py` tests `colab/analyzer.py`.
- Name tests descriptively: `test_analyze_resolves_local_import`, `test_analyze_detects_circular_dependency`.
- Mock at the subprocess level for ColabSession tests (verify correct CLI commands are constructed).
- Integration tests with real Colab are manual for MVP.
