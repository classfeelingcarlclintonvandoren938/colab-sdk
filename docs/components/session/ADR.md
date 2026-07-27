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

## Why inline files instead of upload

Source files are delivered inline (base64-encoded in the wrapper code sent via `colab exec` stdin) rather than uploaded as a `.tar.gz` artifact. This removes the `colab upload` dependency from the hot path, which was unreliable in practice (`colab upload` sometimes exits with code 1 without a clear error message).

Inline delivery also simplifies the pipeline from 9 steps to 6, eliminates the extraction step on the VM, and keeps all file transfer within a single `colab exec` call. The `colab upload` command is still available for explicit file transfer (`app.upload()`), but it is no longer part of the execution pipeline.

This decision trades larger wrapper code (base64 overhead) for reduced latency and fewer failure modes. For projects with many files (>50), the wrapper size may become a concern — at that point, an upload-based fallback could be re-introduced as an optimization.

## References

- `components/session/SPEC.md` — Full specification
- `docs/foundation/ADR/002-google-colab-cli.md` — Why CLI as backend
