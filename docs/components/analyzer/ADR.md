# Analyzer — ADR

> Component-specific decisions for the Analyzer.

---

## Wildcard Import

`from utils import *` cannot be resolved statically. Including the entire package is the conservative choice. A warning is emitted so the user knows the optimization was partially defeated.

## Conditional Import

Static analysis cannot determine which branch of a conditional will be taken. Including both branches guarantees the function can execute regardless of runtime conditions. The cost is a few extra files in the artifact.

## Dynamic Import

`importlib.import_module(name)` is inherently unresolvable statically. The analyzer emits a warning and moves on. The user must ensure the target module is available. This is a fundamental limitation of static analysis.

## Circular Dependency

Python allows circular imports as long as they are structured correctly. The analyzer's `visited_modules` set prevents infinite recursion. The module is only analyzed once. This matches Python's own import behavior.

## Why not use a third-party dependency analyzer

Tools like `modulegraph`, `pylint`, and `mypy` can analyze dependencies, but they operate at a different level of abstraction (linting, type checking). Building our own AST-based analyzer gives us:
- Full control over the manifest format
- No external dependency in the execution path
- Deterministic behavior tied to our specific needs
- Minimal overhead (no need to install a full linting tool)

## References

- `components/analyzer/SPEC.md` — Full specification
- `docs/protocols/manifest-schema.md` — Manifest format
