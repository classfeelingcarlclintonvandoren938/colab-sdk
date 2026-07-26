# Function (RemoteFunction) — ADR

> Component-specific decisions for RemoteFunction.

---

## Why Function holds a reference to App

When `.remote()` is called, the function needs access to the execution infrastructure (engine, session). The simplest way to provide this is a reference to the owning `App`:

```python
class RemoteFunction:
    def remote(self, *args, **kwargs):
        return self._app.engine.execute(self, args, kwargs)
```

The alternative (registry pattern with function IDs) would add indirection without benefit at this scale.

## Why metadata is stored on Function, not App

Each function can have different metadata (GPU override, timeout). Storing metadata on the function object keeps it colocated with the function definition, which is more natural than a separate registry on the App.

## Why args/kwargs must be JSON-serializable

Arguments are serialized into `runner.py` as JSON. This is a deliberate limitation: complex objects (file handles, database connections) cannot be passed to remote functions. Users must pass serializable data and reconstruct complex objects inside the remote function.

This matches the behavior of Modal, Ray, and similar frameworks.

## References

- `docs/protocols/stdout-protocol.md` — Result serialization format
