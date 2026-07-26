# Architecture — Colab Client

> System design overview. All components, their responsibilities, and how they communicate.

---

## System Context

```
┌─────────────────────────────────────┐
│         User's Machine              │
│                                     │
│  ┌──────┐  ┌──────────────────┐     │
│  │ App  │  │ @app.function    │     │
│  └──┬───┘  └────────┬─────────┘     │
│     │               │               │
│     ▼               ▼               │
│  ┌──────────────────────────┐       │
│  │    Execution Engine      │       │
│  │   (orchestration only)   │       │
│  └───┬──────┬───────┬──────┘       │
│      │      │       │              │
│      ▼      ▼       ▼              │
│  ┌────┐ ┌──────┐ ┌───────────┐    │
│  │Ana-│ │Pack- │ │Colab      │    │
│  │lyzr│ │ager  │ │Session    │    │
│  └────┘ └──────┘ └─────┬─────┘    │
│                         │          │
└─────────────────────────┼──────────┘
                          │ google-colab-cli
                          ▼
              ┌───────────────────────┐
              │   Google Colab VM     │
              │                       │
              │  GPU (T4/L4/A100/..)  │
              │  ┌─────────────────┐  │
              │  │ artifact.tar.gz │  │
              │  │ runner.py exec()│  │
              │  └─────────────────┘  │
              └───────────────────────┘
```

---

## Component Responsibilities

### App

SDK entry point. Holds all state.

- Holds configuration (GPU type, idle timeout)
- Owns the `ExecutionEngine` instance
- Owns the `ColabSession` (one session per App)
- Registers functions via `@app.function` decorator
- Provides `login()` and `shutdown()` lifecycle methods
- Provides `upload()`, `download()`, and `secret()` convenience methods

Does **not** execute code, analyze dependencies, or communicate with Google.

### RemoteFunction

Created by `@app.function`. A thin handle with metadata.

- Stores metadata (name, GPU, timeout, source file)
- Holds a reference to the owning `App`
- Delegates `.remote()` to `App.engine.execute(self)`

Does **not** own state beyond metadata. Does not know about sessions or VMs.

### Execution Engine

Orchestrates the execution pipeline. Calls other components in order.

Pipeline: Validate → Analyze → Package → Ensure Session → Upload → Install → Execute → Parse Result → Return

- Orchestrates the pipeline
- Handles errors at each stage
- Manages retries (session dead → re-create)

Does **not** analyze code, package files, or communicate with Colab directly.

### Analyzer

Static dependency analysis. Produces an `ExecutionManifest`.

- Parses function source to AST
- Resolves local imports (recursive DFS)
- Classifies: local file vs external package
- Handles edge cases: wildcard, conditional, dynamic, circular imports
- Outputs: `ExecutionManifest { files: [...], requirements: [...] }`

Does **not** package, upload, or execute anything.

### Packager

Consumes an `ExecutionManifest` and produces a `.tar.gz` artifact.

- Collects files listed in the manifest
- Generates `runner.py` (entry point with result serialization)
- Bundles into deterministic `.tar.gz`
- Computes artifact hash

Does **not** analyze dependencies or upload artifacts.

### ColabSession

Thin wrapper around `google-colab-cli`. The only component that talks to Google.

- `start(name, gpu)` → `colab new -s <name> --gpu <type>`
- `execute(name, file)` → `colab exec -s <name> -f <file>` (streams output)
- `upload(name, local, remote)` → `colab upload`
- `download(name, remote, local)` → `colab download`
- `install(name, packages)` → `colab install`
- `status(name)` → `colab status -s <name>`
- `stop(name)` → `colab stop -s <name>`

Does **not** analyze, package, or orchestrate.

---

## Session Lifecycle

```
App()
  │
  ▼
[no session]
  │
  ▼
first .remote()
  │
  ▼
ensure_session()
  │
  ├── colab new --gpu T4        (if no session exists)
  └── colab status -s <name>    (health check if session exists)
  │
  ▼
execute()
  │
  ▼
[reuse session for subsequent .remote() calls]
  │
  ▼
app.shutdown() OR idle timeout
  │
  ▼
colab stop -s <name>
```

- **Lazy creation**: Session only boots on first `.remote()`.
- **Health check**: Each `.remote()` verifies the session is alive. If dead, creates new.
- **No auto-shutdown**: Script exit does not stop the session. Session persists until `app.shutdown()` or Colab's internal timeout.
- **Idle timeout**: Reserved for future use. Currently, session lifetime is managed by `google-colab-cli`'s keep-alive (60s ping, 24h max). The `App(idle_timeout="30m")` parameter is a placeholder — idle timeout will be implemented as a background check if needed post-MVP.
- **Keep-alive**: Managed by `google-colab-cli` (60s ping, 24h max).

---

## Communication Flow

### SDK → Colab VM (via google-colab-cli)

| Action | CLI Command |
|---|---|
| Create session | `colab new -s <name> --gpu <type>` |
| Execute code | `colab exec -s <name> -f <file>` |
| Upload file | `colab upload -s <name> <local> <remote>` |
| Download file | `colab download -s <name> <remote> <local>` |
| Install packages | `colab install -s <name> <pkg>` |
| Check status | `colab status -s <name>` |
| Stop session | `colab stop -s <name>` |

### Colab VM → SDK (runtime output)

`colab exec` streams stdout/stderr via the Jupyter kernel protocol. The SDK parses structured markers:

```
stdout: __LAZY_LOG__:<message>
stdout: __LAZY_PROGRESS__:<value>
stdout: __LAZY_RESULT__:<json>
stderr: __LAZY_ERROR__:<json>
```

See `protocols/stdout-protocol.md` for details.

---

## Data Flow — Core Execution

### Single .remote() with Secrets

```
1. Engine.validate(train)
   → Check metadata, GPU, timeout

2. Analyzer.analyze(train)
   → Parse AST, resolve imports
   → ExecutionManifest

3. Packager.build(manifest, args, kwargs, app.secrets)
   → Copy files, generate runner.py with os.environ injection
   → artifact.tar.gz + hash

4. ColabSession.ensure_session(name="lazy", gpu="T4")
   → status() check → if dead/missing: start() with GPU

5. ColabSession.ensure_requirements(hash, packages)
   → SHA256 hash of sorted requirements
   → Skip if hash cached on VM
   → colab install if new

6. ColabSession.upload(artifact)
   → colab upload artifact.tar.gz

7. ColabSession.execute("runner.py")
   → colab exec -s <name> -f runner.py
   → Stream stdout in real-time

8. Engine.parse_result(stdout)
   → Find __LAZY_RESULT__ marker
   → Deserialize JSON
   → Return to caller
```

### File Transfer (Independent of .remote())

```
app.upload("model.pt")
  → Engine.ensure_session()          # lazy create if needed
  → ColabSession.upload("model.pt")
  → colab upload -s <name> <local> <remote>

app.download("checkpoint.pt")
  → Engine.ensure_session()          # lazy create if needed
  → ColabSession.download(...)
  → colab download -s <name> <remote> <local>
```

---

## Glossary

| Term | Definition |
|---|---|
| **App** | SDK entry point. Holds configuration, engine, and session. |
| **RemoteFunction** | Created by `@app.function`. A handle with metadata that delegates `.remote()` to the engine. |
| **ExecutionManifest** | Output of the Analyzer. Contains a list of required files and external packages. |
| **Artifact** | A `.tar.gz` file produced by the Packager from a Manifest. Contains source files, `runner.py`, and metadata. |
| **runner.py** | Generated entry point script inside the artifact. Imports the target function, executes it, and serializes the result via `__LAZY_*` protocol. |
| **Session** | A persistent Colab VM. Created by `colab new`. Kept alive by `google-colab-cli`'s keep-alive mechanism. |
| **ColabSession** | Python wrapper class around `google-colab-cli` commands. The only component that communicates with Google. |
| **ExecutionEngine** | Orchestrator. Calls Analyzer, Packager, ColabSession in sequence. |
| **google-colab-cli** | Official Google CLI (`pip install google-colab-cli`). Provides `colab new`, `colab exec`, `colab upload`, etc. |
| **keep-alive** | Background daemon spawned by `google-colab-cli` that pings Colab every 60s to prevent idle VM termination. |
| **`__LAZY_*` protocol** | Structured stdout/stderr markers: `__LAZY_RESULT__`, `__LAZY_ERROR__`, `__LAZY_LOG__`, `__LAZY_PROGRESS__`. |
