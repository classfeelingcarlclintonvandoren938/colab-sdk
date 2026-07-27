# Execution Engine — SPEC

> Orchestrates the execution pipeline. Calls Analyzer and ColabSession in sequence.
> Source files are delivered inline (base64-encoded in the wrapper code) — no upload step.

---

## Input

`engine.execute(function_name: str, source_file: Path, args: tuple, kwargs: dict, secrets: dict[str, str] | None = None, *, session_name: str, gpu: str | None, debug: bool = False)`

## Output

The deserialized return value of the remote function. Or raises `RemoteExecutionError` on failure.

## Pipeline

```
execute()
  │
  ├── 1. validate(gpu)
  │     Check: GPU type against known list (T4, L4, A100, H100)
  │
  ├── 2. manifest = analyzer.analyze(function_name, source_file)
  │     Static dependency analysis → ExecutionManifest
  │
  ├── 3. engine._prepare_session(session_name, gpu, manifest)
  │     │
  │     ├── 3a. session.ensure_session(name, gpu)
  │     │     colab new --gpu <gpu> (if dead/missing)
  │     │     colab status -s <name> (health check)
  │     │
  │     └── 3b. session.ensure_requirements(hash, packages)
  │           Skip if hash cached, else colab install
  │
  ├── 4. engine._execute_with_retry(session_name, manifest, secrets, args, kwargs, debug)
  │     │
  │     ├── 4a. wrapper = engine._build_wrapper(manifest, secrets, args, kwargs)
  │     │     Base64-encode all source files + inject secrets + function call
  │     │     Produces a self-contained Python script
  │     │
  │     ├── 4b. session.run_code(session_name, wrapper)
  │     │     colab exec -s <name> (stdin, no temp file needed)
  │     │     Returns a generator yielding stdout lines in real-time
  │     │
  │     └── 4c. classify(stream)
  │           Iterate the generator, yield LogMessage/ProgressMessage
  │           Return ResultMessage or raise RemoteExecutionError
  │
  └── 5. return result.value
```

## Error Handling

| Stage | Error | Action |
|---|---|---|
| 1. validate | Invalid GPU | Raise `ValidationError` immediately |
| 2. analyze | Circular import, missing module | Raise `AnalysisError` |
| 3a. session | Session dead after creation | Raise `SessionError` |
| 3a. session | Auth expired, quota exceeded | Raise `AuthError` or `SessionError` |
| 3a. session | GPU mismatch | Raise `SessionGpuMismatchError` (not retried) |
| 3b. requirements | Package install failure | Raise `SessionError` |
| 4c. execute | Session dead | Retry: create new session, re-execute |
| 4c. execute | Function exception | Raise `RemoteExecutionError` with traceback |
| 4c. parse | Invalid result format | Raise `ProtocolError` |
| 4c. parse | Stream ends without marker | Raise `ProtocolError` |

## GPU Collision

If a function specifies a GPU different from the `App`'s default GPU:

| Scenario | Behavior |
|---|---|
| First call, no session | Session created with the function's GPU |
| Subsequent call, same GPU | Reuses existing session |
| Subsequent call, different GPU | Raises `SessionGpuMismatchError` — one session = one GPU type |

The user must stop the current session and create a new one to change GPU types.

## Retry Logic

- **Session dead**: If the session is dead during execution, create a new session and retry once.
- **Transient failures** (prepare_session): Network timeouts. Retry up to 3 times with exponential backoff.
- **Non-retriable failures**: Invalid configuration, auth failure, function exception. Do not retry.

## Debug Mode

When `debug=True`:
- Every raw line from the VM is printed to stderr with `[colab-raw]` prefix
- The final `__LAZY_RESULT__` value is printed
- `RemoteExecutionError` is logged before re-raising
- Useful for diagnosing remote execution failures without modifying code

## Performance Notes

- Steps 3a-3b are skipped on subsequent `.remote()` calls if the session is alive and requirements are cached.
- Step 4b (execute) is the only synchronous wait. All other steps are fast (sub-second).
- No file upload overhead — source files are base64-encoded inline.

## What Engine Does NOT Do

- Analyze code directly (delegates to Analyzer)
- Package files directly (delegates to Packager — only for local caching, not in hot path)
- Communicate with Google directly (delegates to ColabSession)
- Manage network servers

## Dependencies

- `Analyzer`
- `ColabSession`

## Protocol Dependencies

- `protocols/manifest-schema.md` — Uses `ExecutionManifest` from Analyzer
- `protocols/stdout-protocol.md` — Parses `__LAZY_*` markers from output

## References

- `docs/foundation/ARCHITECTURE.md` — Pipeline overview
- `docs/foundation/ADR/003-static-analysis.md` — Why Analyzer exists
- `docs/foundation/ADR/006-persistent-session.md` — Why session is reused
