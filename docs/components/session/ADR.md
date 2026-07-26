# Session (ColabSession) — ADR

> Component-specific decisions for ColabSession.

---

## Why subprocess instead of Python API

`google-colab-cli` is distributed as a CLI tool, not a Python library. Its primary interface is command-line commands. The cleanest way to interact with it is via `subprocess`.

If Google later exposes a Python API for `google-colab-cli`, we can replace the subprocess calls with direct Python calls without changing the `ColabSession` interface. The `SPEC.md` defines the behavior, not the implementation.

## Why no session pool

One App = one session. There is no session pooling, no load balancing, no session reuse across `App` instances. Each `App` manages its own session independently. Session pooling is a post-v1 concern (if ever).

## Why execute() returns a generator

`colab exec` streams stdout in real-time via the Jupyter kernel's iopub channel. Yielding lines as they arrive allows the Engine to forward logs and progress to the caller without waiting for execution to complete. A generator is the simplest streaming abstraction in Python.

## Why no persistent SSH or direct connection

All communication goes through `google-colab-cli`, which manages its own connection (WebSocket to Jupyter kernel for `colab exec`, TFE tunnel for keep-alive). There is no persistent SSH session, no direct TCP connection, and no custom protocol. This is intentional: delegating connectivity to the CLI reduces the SDK's attack surface and maintenance burden.

## Why upload before execute

The artifact must be on the VM before execution. `colab upload` transfers the `.tar.gz`, then `colab exec` triggers extraction and execution. This two-step process is consistent with how `google-colab-cli` works and provides clear error boundaries: if upload fails, the error is about upload, not execution.

## References

- `components/session/SPEC.md` — Full specification
- `docs/foundation/ADR/002-google-colab-cli.md` — Why CLI as backend
