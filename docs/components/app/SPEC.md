# App — SPEC

> SDK entry point. Holds configuration, owns the engine and session.

---

## Input

Configuration parameters passed at construction:

| Param | Type | Default | Description |
|---|---|---|---|
| `gpu` | `str \| None` | `None` | GPU type: `"T4"`, `"L4"`, `"A100"`, `"H100"`. `None` = CPU. |
| `idle_timeout` | `str \| None` | `"30m"` | Session idle timeout before auto-shutdown. Format: `"30m"`, `"1h"`. |
| `session_name` | `str \| None` | `None` | Optional name for the Colab session. Auto-generated if omitted. |

## Output

A configured `App` instance ready to register functions and execute them remotely.

## Behavior

### Construction (`App(...)`)

- Validates GPU type against known list
- Validates idle_timeout format
- Creates an `ExecutionEngine` instance (injected with `Analyzer` + `ColabSession`)
- Creates a `ColabSession` instance (lazy: no VM created)
- `App` excludes itself from dependency analysis so its internal imports (e.g. `dotenv`) don't leak into the remote manifest

### `app.login()`

Triggers authentication with Google Colab. Calls `google-colab-cli`'s auth flow.

- **Optional**: If the user is already authenticated, this is a no-op.
- **Auto-triggered**: The first `colab` command that requires auth triggers the OAuth flow automatically.
- **Idempotent**: Safe to call multiple times.

### `@app.function(**kwargs)`

Decorator that registers a function for remote execution. Supports two forms:

```python
# Bare decorator (no arguments)
@app.function
def train():
    ...

# Decorator with arguments
@app.function(gpu="T4", timeout=300)
def train():
    ...

# Non-decorator form (for pre-defined functions)
hello = app.function(hello)
```

Returns a `RemoteFunction` instance.

See `components/function/SPEC.md` for details.

### `remote(debug=False)`

Every `RemoteFunction` exposes a `.remote()` method:

```python
result = train.remote(epochs=10, lr=0.01)
```

- `*args` / `**kwargs` are forwarded to the remote function
- **All args/kwargs must be JSON-serialisable** (they are embedded in the wrapper code)
- `debug=True` prints every raw line from the VM to stderr with `[colab-raw]` prefix
- Returns the deserialised return value of the remote function
- Raises `RemoteExecutionError` if the remote function raises

### `app.shutdown()`

Explicitly terminates the Colab session.

- Calls `ColabSession.stop()`
- If no session exists, this is a no-op
- After shutdown, calling `.remote()` again creates a new session

### `app.upload(local_path, remote_path=None)`

Uploads a local file or directory to the Colab VM.

```python
app.upload("model.pt")
app.upload("config.yaml", "/content/config.yaml")
app.upload("data/", "/content/data/")
```

- `local_path` — path to a local file or directory
- `remote_path` — destination path on the Colab VM (defaults to `/content/<filename>`)
- Delegates to `ColabSession.upload()`
- Requires an active session (auto-creates if needed)

### `app.download(remote_path, local_path=None)`

Downloads a file from the Colab VM to the local machine.

```python
app.download("checkpoint.pt")
app.download("/content/logs/training.log", "./training.log")
```

- `remote_path` — path to the file on the Colab VM
- `local_path` — destination path locally (defaults to `./<filename>`)
- Delegates to `ColabSession.download()`
- Requires an active session

### `app.secret(name, value)`

Injects an environment variable into the remote execution environment.

```python
app.secret("HF_TOKEN", "hf_abc123")
app.secret("WANDB_API_KEY", "wandb_xyz")
```

- Stores the secret locally; on the next `.remote()` call, the wrapper code is generated with `os.environ[<name>] = <value>` before the function executes
- Secrets are **not** sent to the VM until the next `.remote()` — they are embedded into the inline wrapper code
- Idempotent: calling `app.secret("KEY", "val")` twice overwrites with the latest value
- Not persisted across script restarts (must be set each session)

## Edge Cases

- **Double shutdown**: `app.shutdown()` called twice is safe (idempotent).
- **No session**: `app.shutdown()` with no active session is a no-op.
- **Authentication failure**: If `app.login()` fails, `.remote()` will also fail with an explicit auth error.
- **Upload before session**: `app.upload()` auto-creates the session if not already active (same lazy creation as `.remote()`).
- **Non-existent local file**: `app.upload()` raises `FileNotFoundError`.
- **Missing remote file**: `app.download()` raises `DownloadError` if the remote file doesn't exist.
- **Function module import**: Functions defined at module level (not inside `main()`) can be imported on the VM without SDK dependency. Prefer defining remote functions outside SDK-using code.

## What App Does NOT Do

- Execute code directly
- Analyze dependencies
- Package artifacts
- Communicate with Google directly

## Dependencies

- `ExecutionEngine` (owns one)
- `ColabSession` (owns one)

## Protocol Dependencies

- None directly (delegates to engine)

## References

- `docs/foundation/ARCHITECTURE.md` — Component context
- `docs/foundation/ADR/006-persistent-session.md` — Why persistent session
