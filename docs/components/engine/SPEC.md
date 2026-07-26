# Execution Engine — SPEC

> Orchestrates the execution pipeline. Calls Analyzer, Packager, and ColabSession in sequence.

---

## Input

`engine.execute(function: RemoteFunction, args: tuple, kwargs: dict, secrets: dict[str, str] | None = None)`

## Output

The deserialized return value of the remote function. Or raises `RemoteExecutionError` on failure.

## Pipeline

```
execute()
  │
  ├── 1. validate(function)
  │     Check: function metadata, GPU type, timeout
  │
  ├── 2. manifest = analyzer.analyze(function)
  │     Static dependency analysis → ExecutionManifest
  │
  ├── 3. artifact = packager.build(manifest, args, kwargs, secrets)
  │     Package manifest + args + secrets into artifact.tar.gz
  │     Secrets are inlined into runner.py as os.environ assignments
  │
  ├── 4. session.ensure_session(name=session_name, gpu=gpu)
  │     Uses the function's GPU (overrides App GPU if specified)
  │     If no session: colab new --gpu <gpu>
  │     If existing session with different GPU: raise SessionGpuMismatchError
  │
  ├── 5. session.ensure_requirements(name=session_name,
  │          requirements_hash=manifest.requirements_hash,
  │          packages=manifest.requirements)
  │     Skip if hash cached, else colab install
  │
  ├── 6. session.upload(artifact)
  │     colab upload artifact.tar.gz
  │
  ├── 7. session.execute(artifact.runner_path)
  │     colab exec -s <session> -f runner.py
  │     Returns a generator yielding stdout lines in real-time
  │
  ├── 8. result = parse_result(stream)
  │     Iterate the generator, forward non-prefixed lines as logs
  │     Detect __LAZY_RESULT__ marker, deserialize JSON
  │     Detect __LAZY_ERROR__ marker, raise RemoteExecutionError
  │
  └── 9. return result
```

## Error Handling

| Stage | Error | Action |
|---|---|---|
| 1. validate | Invalid GPU, missing function | Raise `ValidationError` immediately |
| 2. analyze | Circular import, missing module | Raise `AnalysisError` |
| 3. package | File not found | Raise `PackagingError` |
| 4. session | Auth expired, quota exceeded | Raise `AuthError` or `SessionError` |
| 5. requirements | Package install failure | Raise `InstallationError` |
| 6. upload | Upload failure | Raise `UploadError` |
| 7. execute | Session dead | Retry: create new session, re-execute |
| 7. execute | Function exception | Raise `RemoteExecutionError` with traceback |
| 8. parse | Invalid result format | Raise `ProtocolError` |

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
- **Transient failures**: Network timeouts, upload failures. Retry up to 3 times with exponential backoff.
- **Non-retriable failures**: Invalid configuration, auth failure, function exception. Do not retry.

## Performance Notes

- Steps 4-6 are skipped on subsequent `.remote()` calls if the session is alive and requirements are cached.
- Step 7 (execute) is the only synchronous wait. All other steps are fast (sub-second).

## What Engine Does NOT Do

- Analyze code directly (delegates to Analyzer)
- Package files directly (delegates to Packager)
- Communicate with Google directly (delegates to ColabSession)
- Manage network servers

## Dependencies

- `Analyzer`
- `Packager`
- `ColabSession`

## Protocol Dependencies

- `protocols/manifest-schema.md` — Uses `ExecutionManifest` from Analyzer
- `protocols/stdout-protocol.md` — Parses `__LAZY_*` markers from output

## References

- `docs/foundation/ARCHITECTURE.md` — Pipeline overview
- `docs/foundation/ADR/003-static-analysis.md` — Why Analyzer exists
- `docs/foundation/ADR/006-persistent-session.md` — Why session is reused
