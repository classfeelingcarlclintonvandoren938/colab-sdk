# Session (ColabSession) — SPEC

> Thin wrapper around `google-colab-cli`. The only component that communicates with Google.

---

## Input

Created internally by the `App`:

```python
session = ColabSession(name="lazy-gpu")
```

## Output

Methods that wrap `google-colab-cli` commands:

| Method | CLI Command | Returns |
|---|---|---|
| `start(name, gpu)` | `colab new -s <name> --gpu <type>` | None |
| `stop(name)` | `colab stop -s <name>` | None |
| `status(name)` | `colab status -s <name>` | `SessionStatus` (alive/dead + metadata) |
| `ensure_session(name, gpu)` | Composes `status()` + `start()` | None |
| `ensure_requirements(name, requirements_hash, packages)` | Composes hash check + `install()` | None |
| `upload(name, local, remote)` | `colab upload -s <name> <local> <remote>` | None |
| `download(name, remote, local)` | `colab download -s <name> <remote> <local>` | Path to downloaded file |
| `install(name, packages)` | `colab install -s <name> <pkg1> <pkg2>` | None |
| `execute(name, local_file)` | `colab exec -s <name> -f <local_file>` | Generator of stdout lines |
| `write_file(name, remote_path, content)` | N/A (inline content → temp file → upload) | None |

## Session Status

```python
@dataclass
class SessionStatus:
    alive: bool
    name: str
    gpu: str
    created_at: datetime | None
```

## Behavior

### `start(name, gpu)`

Creates a new Colab VM session.

```python
session.start("lazy", "T4")
# → subprocess.run(["colab", "new", "-s", "lazy", "--gpu", "T4"])
```

- Blocks until the session is ready (CLI handles waiting)
- Raises `SessionError` if provisioning fails
- Idempotent: if a session with this name already exists and is alive, this is a no-op

### `stop(name)`

Terminates the session and clean up the keep-alive daemon.

```python
session.stop("lazy")
# → subprocess.run(["colab", "stop", "-s", "lazy"])
```

- Idempotent: calling stop on a non-existent session is safe
- Raises `SessionError` if the CLI fails

### `status(name)`

Checks if the session is alive.

```python
status = session.status("lazy")
# → subprocess.run(["colab", "status", "-s", "lazy"])
```

- Returns `SessionStatus(alive=True, ...)` if the session exists and is healthy
- Returns `SessionStatus(alive=False, ...)` if the session is dead or doesn't exist
- Used by `ensure_session()` before every `.remote()` call

### `ensure_session(name, gpu)`

Composes `status()` and `start()` to ensure a session exists and is healthy.

```python
session.ensure_session("lazy", "T4")
# → status("lazy") → if dead or missing: start("lazy", "T4")
```

- Calls `status(name)` first to check session health
- If session exists and is alive: no-op
- If session is dead or doesn't exist: calls `start(name, gpu)`
- This is the primary method used by Engine — replaces manual status/start calls

### `ensure_requirements(name, requirements_hash, packages)`

Installs packages only if the hash is not cached on the VM.

```python
session.ensure_requirements("lazy", "a83bf9...", ["torch", "numpy"])
# → check if hash "a83bf9..." exists at ~/.colab-client/hashes/
# → if not: install("lazy", "torch", "numpy") and save hash
```

- Checks if `requirements_hash` already exists in a known location on the VM
- If cached: skip installation entirely
- If not cached: calls `install(name, packages)` and persists the hash
- The hash check is implemented by executing a small probe script on the VM

### `execute(name, local_file)`

Executes a local Python file on the Colab VM. **Returns a generator** — the Engine iterates over it line by line.

```python
for line in session.execute("lazy", "runner.py"):
    print(line)  # Real-time output from colab exec
```

- `local_file` is read by `colab exec` and transmitted to the VM's Jupyter kernel
- Stdout is yielded line by line as the CLI receives it
- Stderr is captured separately and forwarded to the caller
- Exits after the kernel completes execution
- Raises `RemoteExecutionError` if the CLI exits with non-zero status

### `upload(name, local, remote)`

Uploads a local file to the Colab VM.

```python
session.upload("lazy", "artifact.tar.gz", "/content/artifact.tar.gz")
```

### `download(name, remote, local)`

Downloads a file from the Colab VM to the local machine.

### `install(name, packages)`

Installs Python packages on the Colab VM.

```python
session.install("lazy", "torch", "numpy")
```

### `write_file(name, remote_path, content)`

Writes a string or bytes to a file on the Colab VM without a local intermediate file.

```python
session.write_file("lazy", "/content/.env", "HF_TOKEN=hf_abc123")
```

- Creates a temporary local file with the content, uploads it, then removes the temp file
- Used internally by the engine to inject secrets before execution
- Not typically called directly by users

---

## Precondition: CLI Availability

Before any CLI command, the SDK checks that `google-colab-cli` is installed by verifying the `colab` command is on `PATH`. If not found, a clear error is raised:

```python
import shutil

if not shutil.which("colab"):
    raise SessionError(
        "google-colab-cli is not installed. "
        "Run: pip install google-colab-cli"
    )
```

This check runs once during construction (`ColabSession.__init__`). It ensures the **Fail Fast** principle: users learn about the missing dependency immediately, not after a `FileNotFoundError` deep in execution.

## Implementation Detail

All methods shell out to `google-colab-cli` via `subprocess.run()` or `subprocess.Popen()`:

```python
import subprocess

def start(self, name, gpu):
    cmd = ["colab", "new", "-s", name]
    if gpu:
        cmd.extend(["--gpu", gpu])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SessionError(result.stderr)
```

The `execute()` method uses `Popen` with streaming:

```python
def execute(self, name, local_file):
    cmd = ["colab", "exec", "-s", name, "-f", local_file]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        for line in proc.stdout:
            yield line.rstrip()
```

---

## What Session Does NOT Do

- Analyze code
- Package artifacts
- Orchestrate pipelines
- Manage network servers

## Dependencies

- `google-colab-cli` (external pip package)

## Protocol Dependencies

- `protocols/artifact-format.md` — Uploads and executes the artifact
- `protocols/stdout-protocol.md` — Passes through `__LAZY_*` output from `execute()`

## References

- `docs/foundation/ADR/002-google-colab-cli.md` — Why CLI as backend
- `docs/foundation/ADR/006-persistent-session.md` — Why persistent session
