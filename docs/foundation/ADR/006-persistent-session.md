# ADR-006: Persistent Session with Lazy Creation

**Status:** Accepted

---

## Context

The project needed to decide how a Colab VM maps to the SDK's `App` and `Function` abstractions.

Three session models were considered:
1. **Ephemeral per-call**: Every `.remote()` provisions a fresh VM via `colab run`, executes, and tears down.
2. **Persistent with eager creation**: `App()` immediately creates a VM via `colab new`.
3. **Persistent with lazy creation**: Session is created on the first `.remote()` call and reused for subsequent calls until `app.shutdown()` or idle timeout.

## Decision

**Persistent session with lazy creation.** One App = one persistent Colab VM. The VM is created on the first `.remote()` call (not at `App()` construction). It is reused for all subsequent `.remote()` calls until explicitly shut down or timed out.

```python
app = App()       # No VM created yet
train.remote()    # First call: colab new --gpu T4
evaluate.remote() # Second call: reuses same VM
predict.remote()  # Third call: reuses same VM
app.shutdown()    # Explicit: colab stop
```

## Rationale

- **Mental model**: Users think "I have one remote machine." This is more intuitive than "I submit individual jobs."
- **Performance**: Subsequent calls are near-instant (~1s) because the VM is warm, packages are installed, and filesystem state persists.
- **Caching**: The VM caches installed packages, downloaded models, and generated data across calls.
- **Model alignment**: This matches how Modal, RunPod, and Beam work. Users familiar with those platforms will feel at home.
- **Lazy creation**: Avoids provisioning a VM until the user actually calls `.remote()`. User can construct `App()` and register functions without paying a startup cost.

## Trade-offs

- **Lifecycle management**: The VM persists after the Python script exits. Users must call `app.shutdown()` or rely on idle timeout. Ephemeral per-call avoids this entirely.
- **State leakage**: Data written to the VM filesystem persists across calls. A later `.remote()` could accidentally use stale state from an earlier call.
- **Keep-alive cost**: The VM consumes Colab compute units even when idle (though `google-colab-cli`'s keep-alive is lightweight).

## Consequences

- `App()` does not accept a `provider` parameter (see ADR-001).
- `App()` does not accept a `session` parameter (only one session per App).
- `App.shutdown()` is the explicit teardown method. No `atexit` hook.
- Idle timeout is configurable via `App(idle_timeout="30m")`. Default is 30 minutes.
- The session health check runs on every `.remote()`. If the session is dead, a new one is created automatically.

## Alternatives Considered

**Ephemeral per-call.** Rejected because:
- Each call is 20-30 seconds (provision + install + execute + teardown).
- No caching: packages install every time, files upload every time.
- Poor mental model: users don't think in terms of "submit job, wait, submit another job."

**Persistent with eager creation.** Rejected because:
- `App()` would block for 10-30 seconds waiting for VM provisioning.
- The user may construct `App()` and never call `.remote()`, wasting resources.
- Violates the "lazy by default" principle.

## References

- CONSTITUTION.md, Rule 6 (Lazy by Default)
- CONSTITUTION.md, Rule 10 (Explicit Lifecycle)
- CONSTITUTION.md, Rule 11 (One App, One Session)
- `docs/components/session/SPEC.md`
