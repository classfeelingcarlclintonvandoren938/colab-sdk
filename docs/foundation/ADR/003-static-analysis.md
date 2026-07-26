# ADR-003: Static Dependency Analysis

**Status:** Accepted

---

## Context

When executing a function remotely, the framework must decide which files to transfer to the Colab VM.

Three approaches were possible:
1. **Upload the entire project** — simplest, but transfers unnecessary files (tests, data, docs, configs).
2. **User specifies dependencies manually** — flexible, but creates maintenance burden and user friction.
3. **Static dependency analysis** — parse the function's source code, trace its imports, and upload only what's needed.

## Decision

Use **static dependency analysis** (approach 3). The Analyzer component parses the function's source code using Python's `ast` module, resolves all local imports recursively, and produces an `ExecutionManifest` containing only the required files and external packages.

```
Function source → AST parse → Resolve imports → Recursive DFS → ExecutionManifest
```

## Rationale

- **Minimum upload**: Only files that the function transitively imports are transferred. A simple function in a large project uploads only kilobytes.
- **Automatic**: No user configuration needed. No `manifest.yaml`, no `lazy_include.txt`, no manual dependency lists.
- **Deterministic**: Given the same function and project structure, the same manifest is produced every time. Enables caching and reproducible builds.
- **Fast**: Static analysis is near-instantaneous. No code execution, no package download, no runtime inspection.
- **Standard Python**: Uses `ast.Import` and `ast.ImportFrom` nodes. No custom parser, no third-party analysis tool.

## Trade-offs

- **Static analysis is incomplete by nature**:
  - Dynamic imports (`importlib.import_module()`) cannot be resolved. Emits a warning, user must manually ensure the module is available.
  - Conditional imports (`if DEBUG: from x import y`) include both branches, potentially transferring unused files.
  - Wildcard imports (`from utils import *`) include the entire package, defeating the optimization for that subtree.
- **Does not handle runtime dependencies**: If a function dynamically loads a file based on user input, the analyzer cannot detect it.

## Consequences

- The Analyzer component is a required part of the execution pipeline.
- Analyzer does **not** package or upload — it produces a Manifest, which the Packager consumes.
- The Analyzer supports: `import x`, `import x as y`, `from a import b`, `from a import *`.
- The Analyzer handles: circular dependencies (visited set), conditional imports (both branches), wildcard imports (entire package + warning), dynamic imports (warning only).
- External packages are recorded as requirements, not uploaded.

## Alternatives Considered

**Upload entire project.** Rejected because it violates the product principle of minimum upload. A project with 100MB of test data would upload everything for a 10-line function.

**Runtime tracing.** Rejected because it requires executing the function to discover dependencies, which is circular (we need the dependencies to execute the function).

**User-specified manifest.** Rejected because it creates maintenance burden and user friction, violating the "minimize user friction" principle.

## References

- CONSTITUTION.md, Rule 6 (Lazy by Default)
- CONSTITUTION.md, Rule 9 (Deterministic Artifacts)
- CONSTITUTION.md, Rule 12 (Never Upload the Whole Project)
- `docs/protocols/manifest-schema.md`
- `docs/components/analyzer/SPEC.md`
