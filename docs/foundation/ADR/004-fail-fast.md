# ADR-004: Fail Fast Validation

**Status:** Accepted

---

## Context

When a user provides invalid configuration (wrong GPU type, missing function, unauthenticated session), the framework must decide when to report the error.

Two approaches:
1. **Fail fast** — Validate as early as possible. At decoration time, at construction time, at import time. Report errors before execution.
2. **Fail late** — Defer validation to runtime. Let the error surface when `.remote()` is called, or worse, when the Colab VM tries to execute.

## Decision

**Fail fast.** Validate configuration at the earliest possible moment.

| Validation | When | What is checked |
|---|---|---|
| GPU type | `App(gpu="T4")` | GPU string is valid (T4, L4, A100, H100) |
| Function signature | `@app.function()` | Function is callable, metadata is valid |
| Import resolution | Analyzer runs | Circular imports, missing local modules |
| Authentication | Before execution | User is authenticated with `google-colab-cli` |
| Session health | Before execution | Session VM is alive and responsive |

## Rationale

- **Immediate feedback**: A typo in GPU type is caught at construction time, not 30 seconds later when the Colab VM boots.
- **Better developer experience**: Errors surface in the editor/IDE, not in a remote execution log.
- **Faster iteration**: The developer fixes the error, re-runs, and continues. No waiting for VM provisioning to discover a simple mistake.
- **Clearer error messages**: Errors at the point of misconfiguration have more context than errors at the point of failure.

## Trade-offs

- **Slightly more code**: Validation logic is duplicated at multiple levels (constructor, decorator, engine) rather than centralized at execution time.
- **Not all errors can be caught early**: Runtime errors (function raises exception, Colab quota exceeded) will always surface at execution time. The framework accepts this.

## Consequences

- `App()` validates GPU type at construction.
- `@app.function` validates the decorated object is callable.
- `ExecutionEngine.validate()` runs before the pipeline begins.
- `ColabSession.ensure_session()` checks session health before executing.
- Error messages are specific and actionable: `"Invalid GPU type 'V100'. Supported: T4, L4, A100, H100"`.
- Runtime errors propagate through the `__LAZY_ERROR__` protocol and are surfaced as `RemoteExecutionError`.

## Alternatives Considered

**Validate everything at execution time.** Rejected because it wastes user time and provides worse error messages. A 30-second wait to discover "GPU type 'foo' is invalid" is unacceptable.

**Validate everything at construction time.** Rejected because some validations (authentication, session health) depend on external state that can change between construction and execution.

## References

- CONSTITUTION.md, Rule 4 (Fail Fast)
- `docs/foundation/PRD.md`, Section 11 (Validation Strategy)
- `docs/components/engine/SPEC.md`
