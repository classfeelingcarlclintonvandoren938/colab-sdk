# Session (ColabSession) — SPEC

> Thin wrapper around `google-colab-cli`. The only component that communicates with Google.

---

## Input

Created internally by the `App`:

```python
session = ColabSession()
```

## Precondition: CLI Availability

Before any command, the SDK checks that `google-colab-cli` is installed by verifying the `colab` command is on `PATH`. This check runs once during construction (`ColabSession.__init__`) to **Fail Fast**.

### `.env` Support

`ColabSession.__init__` loads a `.env` file from the current directory (via `python-dotenv`). Users can set:

```bash
# .env
COLAB_BIN_DIR=/home/user/.local/bin
```

When `COLAB_BIN_DIR` is set, the SDK:
1. Extends `PATH` with this directory for all subprocess calls
2. Uses the custom `PATH` when checking `shutil.which("colab")`

This is especially useful for WSL2 installations where `pip install --user` places binaries in `~/.local/bin/`.

### Windows

`google-colab-cli` requires the Unix `termios` module and **does not run on native Windows**. If `sys.platform == "win32"`, `__init__` raises a clear `SessionError` directing the user to install WSL2.

All `subprocess.run()` / `subprocess.Popen()` calls pass `env=self._env` (a copy of `os.environ` with the extended `PATH` when `COLAB_BIN_DIR` is set) to ensure the `colab` binary is found.

## Output

Methods that wrap `google-colab-cli` commands:

| Method | CLI Command | Returns |
|---|---|---|
| `start(name, gpu)` | `colab new -s <name> --gpu <type>` | None |
| `stop(name)` | `colab stop -s <name>` | None |
| `status(name)` | `colab status -s <name>` | `SessionStatus` (alive/dead + metadata) |
| `ensure_session(name, gpu)` | Composes `status()` + `start()` (with post-creation verification) | None |
| `ensure_requirements(name, requirements_hash, packages)` | Composes temp-file probe + `install()` | None |
| `upload(name, local, remote)` | `colab upload -s <name> <local> <remote>` | None |
| `download(name, remote, local)` | `colab download -s <name> <remote> <local>` | Path to downloaded file |
| `install(name, packages)` | `colab install -s <name> <pkg1> <pkg2>` | None |
| `execute(name, local_file)` | `colab exec -s <name> -f <local_file>` | Generator of stdout lines |
| `run_code(name, code)` | `colab exec -s <name>` (stdin piping) | Generator of stdout lines |
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

### `stop(name)`

Terminates the session and clean up the keep-alive daemon.

```python
session.stop("lazy")
# → subprocess.run(["colab", "stop", "-s", "lazy"])
```

- Idempotent: calling stop on a non-existent session is safe
- Raises `SessionError` if the CLI fails

### `status(name)`

Checks if the session is alive using the CLI exit code **and** output text.

```python
status = session.status("lazy")
# → subprocess.run(["colab", "status", "-s", "lazy"], capture_output=True)
```

- Returns `SessionStatus(alive=True, ...)` if exit code is 0 **and** output does not contain "not found" or "no such session"
- Returns `SessionStatus(alive=False, ...)` if exit code is non-zero, or if output contains dead-session indicators
- The output text check catches cases where the CLI returns exit 0 with stale cached state
- **Note:** The `colab status` command does **not** have a `--json` flag, so only basic alive/dead status is available. GPU info is not parsed from the human-readable output.

### `ensure_session(name, gpu)`

Composes `status()` and `start()` to ensure a session exists and is healthy, with post-creation verification.

```python
session.ensure_session("lazy", "T4")
# → status("lazy")
# → if dead or missing: start("lazy", "T4")
# → status("lazy") again to verify
```

- Calls `status(name)` first to check session health
- If session exists and is alive: no-op (fast path)
- If session is dead or doesn't exist: calls `start(name, gpu)`
- **After start**, calls `status()` again to verify the session is actually alive
- Raises `SessionError` if the session is not responsive after creation
- This is the primary method used by Engine

### `ensure_requirements(name, requirements_hash, packages)`

Installs packages only if the hash is not cached on the VM.

```python
session.ensure_requirements("lazy", "a83bf9...", ["torch", "numpy"])
# → write probe script to temp file → colab exec -f <tmp_probe>
# → if exit 0: hash cached, skip
# → if exit 1: install("lazy", "torch", "numpy"), persist hash
```

- Checks if `requirements_hash` already exists as a marker file at `~/.colab-client/hashes/<hash>` on the VM
- If cached: skip installation entirely
- If not cached: calls `install(name, packages)` and persists the hash marker
- The probe is implemented by **writing a temporary Python file** and executing it via `colab exec -f <tmp_file>` (the CLI does **not** support `-c <code>` or stdin piping)

### `execute(name, local_file)`

Executes a local Python file on the Colab VM. **Returns a generator** — the Engine iterates over it line by line.

```python
for line in session.execute("lazy", "runner.py"):
    print(line)  # Real-time output from colab exec
```

- `local_file` is read by `colab exec -f` and transmitted to the VM's Jupyter kernel
- Stdout is yielded line by line as the CLI receives it
- Stderr is captured separately and read on process completion
- Exits after the kernel completes execution
- Raises `SessionError` if the CLI exits with non-zero status

### `run_code(name, code)`

Executes Python code directly on the Colab VM via stdin (no temp file needed).

```python
for line in session.run_code("lazy", "import os; print(os.name)"):
    print(line)  # Real-time output from colab exec
```

- Code is piped to `colab exec` via `stdin` (no `-f` flag)
- Useful for setup steps (extracting archives, injecting secrets) or wrapping function calls
- Same streaming/yield behavior as `execute()`
- Raises `SessionError` if the CLI exits with non-zero status

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
- Used internally by the engine to persist requirement hash markers
- Not typically called directly by users

---

## Implementation Detail

All methods shell out to `google-colab-cli` via `subprocess.run()` or `subprocess.Popen()`. Every subprocess call receives `env=self._env` — a copy of `os.environ` with `PATH` extended by `COLAB_BIN_DIR` when configured.

```python
import subprocess

def start(self, name, gpu):
    cmd = ["colab", "new", "-s", name]
    if gpu:
        cmd.extend(["--gpu", gpu])
    result = subprocess.run(cmd, capture_output=True, text=True, env=self._env)
    if result.returncode != 0:
        raise SessionError(result.stderr)
```

Both `execute()` and `run_code()` share the same `_exec()` helper which uses `Popen` with streaming:

```python
def _exec(self, cmd, stdin_data=None):
    with subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_data else None,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, bufsize=1, env=self._env) as proc:
        if stdin_data is not None and proc.stdin:
            proc.stdin.write(stdin_data)
            proc.stdin.close()

        for line in proc.stdout:
            yield line.rstrip("\n")

        returncode = proc.wait()
        if returncode != 0:
            raise SessionError(...)
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

- `protocols/stdout-protocol.md` — Passes through `__LAZY_*` output from `execute()` / `run_code()`

## References

- `docs/foundation/ADR/002-google-colab-cli.md` — Why CLI as backend
- `docs/foundation/ADR/006-persistent-session.md` — Why persistent session
