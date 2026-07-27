# Function (RemoteFunction) — SPEC

> Created by `@app.function`. A thin handle that holds metadata and delegates `.remote()` to the engine.

---

## Input

Created by decorating a Python function. The decorator supports **two forms**:

**Form 1 — bare decorator (no arguments):**
```python
@app.function
def train(epochs: int, lr: float = 0.01):
    ...
```

**Form 2 — decorator with arguments:**
```python
@app.function(gpu="T4", timeout=300)
def train(epochs: int, lr: float = 0.01):
    ...
```

Decorator parameters (Form 2):

| Param | Type | Default | Description |
|---|---|---|---|
| `gpu` | `str \| None` | `None` | Override GPU type for this specific function |
| `timeout` | `int \| None` | `None` | Execution timeout in seconds |

## Output

A `RemoteFunction` instance with a `.remote()` method.

## Behavior

### Metadata stored

- `name` — Function name (e.g., `"train"`)
- `fn` — The original Python function
- `source_file` — Path to the `.py` file containing the function
- `app` — Reference to the owning `App`
- `gpu` — GPU type (override or inherited from App)
- `timeout` — Execution timeout

### `function.remote(*args, **kwargs)`

Calls `app.engine.execute(self, args, kwargs)` and returns the result.

```python
result = train.remote(epochs=10, lr=0.001)
```

- `args` and `kwargs` are forwarded to the user's function on the Colab VM
- Returns the deserialized return value from `__LAZY_RESULT__`
- Raises `RemoteExecutionError` if the function raises an exception on the VM

## Edge Cases

- **No arguments**: `fn.remote()` with no args is valid.
- **Non-serializable arguments**: Arguments passed to `.remote()` must be JSON-serializable (they are serialized and embedded in the wrapper code sent to the VM).
- **Non-serializable return values**: Return values must also be JSON-serializable — they are wrapped in the `__LAZY_RESULT__` protocol as JSON. Complex Python objects (custom classes, generators, file handles) must be serialized by the user.
- **Overridden GPU**: If the function specifies a GPU different from the App's default, the function's GPU is used. If a session already exists with a different GPU type, a `SessionGpuMismatchError` is raised (see Engine SPEC).

## What RemoteFunction Does NOT Do

- Execute code directly
- Manage sessions
- Analyze dependencies

## References

- `docs/foundation/ARCHITECTURE.md` — Component context
- `docs/components/engine/SPEC.md` — What engine.execute() does
