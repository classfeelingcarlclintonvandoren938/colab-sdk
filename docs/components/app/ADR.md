# App — ADR

> Component-specific decisions for the App.

---

## Why App owns Engine and Session

The App is the single source of truth for all execution state. If both the Engine and Session were independent objects, callers would need to manage them separately:

```python
# Bad: caller manages two objects
engine = ExecutionEngine()
session = ColabSession(...)
result = engine.execute(function, session)
```

Instead, App owns both:

```python
# Good: one object, clear lifecycle
app = App()
result = app.function.remote()
```

## Why login() is optional

Authentication is a prerequisite for execution, not for API construction. The user should be able to construct `App()` and register functions without being forced to authenticate. Authentication is deferred until the first `.remote()` call, consistent with the lazy principle.

## Why no context manager

`with App() as app:` implies a bounded lifecycle, but compute runtimes are long-lived. A user may:
1. Open a Python REPL
2. Create an App
3. Call `.remote()` multiple times over an hour
4. Shut down explicitly

A context manager would force shutdown at the end of the `with` block, which is incorrect for this use case.

## References

- CONSTITUTION.md, Rule 10 (Explicit Lifecycle)
- ADR-006 (Persistent Session)
