# Analyzer — SPEC

> Static dependency analysis. Produces an `ExecutionManifest` from a function.

---

## Input

`analyzer.analyze(function: RemoteFunction) -> ExecutionManifest`

The function's source file is located, parsed, and analyzed recursively.

## Output

An `ExecutionManifest` containing:
- `function_name`: The name of the target function
- `entry_point`: Path to the source file containing the function
- `files`: All local source files required by the function
- `requirements`: All external packages discovered
- `requirements_hash`: SHA256 of sorted requirements
- `warnings`: Non-fatal warnings (wildcard imports, dynamic imports)

---

## Pipeline

```
analyze(function)
  │
  ├── 1. Locate source file
  │     Find the .py file containing the function definition
  │
  ├── 2. Parse AST
  │     Extract ast.Import and ast.ImportFrom nodes
  │     Build import table: {symbol → module_path}
  │
  ├── 3. Analyze function body
  │     Walk the function's AST body
  │     Collect all referenced symbols
  │
  ├── 4. Resolve dependencies (recursive DFS)
  │     For each symbol:
  │       Look up in import table
  │       Classify as local module or external package
  │       If local: add to manifest, open file, repeat from step 2
  │       If external: add to requirements
  │
  ├── 5. Handle special cases
  │     Wildcard imports, conditional imports, dynamic imports
  │
  └── 6. Return ExecutionManifest
```

---

## Import Resolution

### Supported patterns

```python
import torch                          # External → requirements
import numpy as np                    # External → requirements
from training import trainer          # Local → recursive analysis
from utils.model import Builder       # Local → recursive analysis
from utils import model               # Local → recursive analysis
```

The analyzer uses `ast.Import` and `ast.ImportFrom` nodes. It does **not** evaluate code, resolve dynamic attributes, or execute imports.

### Local vs External classification

Uses `importlib.util.find_spec(module_name)` to determine if a module is local (returns a spec with `origin` in the project directory) or external (returns a spec with `origin` in `site-packages`).

---

## Special Cases

### Wildcard import (`from utils import *`)

- Cannot resolve individual symbols
- Includes the entire `utils/` package in the manifest
- Appends a warning to `manifest.warnings`
- **Risk**: May include many unnecessary files

```python
from utils import *
# → Warning: Wildcard import at app.py:5
# → Adds: utils/__init__.py, utils/model.py, utils/image.py, utils/data.py
```

### Conditional import

```python
if DEBUG:
    from utils import model
else:
    from utils import image
```

- Includes **both** branches' dependencies
- Safer than trying to determine which branch is active (impossible statically)
- May include unnecessary files, but guarantees correctness

### Dynamic import (`importlib.import_module()`)

```python
module = importlib.import_module(name)
```

- Cannot resolve statically
- Appends a warning to `manifest.warnings`
- Does NOT add any files for this import
- User must ensure the dynamically loaded module is available on the VM

### Circular dependency

```python
# A.py
from B import b

# B.py
from A import a
```

- Uses a `visited_modules` set to track already-analyzed modules
- Skips re-analysis of visited modules
- Does NOT add duplicate entries to the manifest

---

## Edge Cases

- **Non-Python files**: If a function references a `.txt`, `.csv`, `.json` file via `open()` or `pathlib`, the analyzer does not detect it. Users must ensure such files are available on the VM. Future enhancement: analyze `open()` calls and include referenced data files.
- **Dynamically generated code**: Code constructed via `eval()`, `exec()`, or `__import__()` is invisible to the analyzer.
- **C extension modules**: Detected as external packages (correct behavior — they cannot be uploaded as source).
- **Namespace packages**: Handled by `find_spec()`. If the spec resolves to a namespace package, the analyzer warns and includes the package.

---

## What Analyzer Does NOT Do

- Package files
- Upload anything
- Execute code
- Resolve runtime dependencies
- Analyze data files

## Protocol Dependencies

- `protocols/manifest-schema.md` — Produces `ExecutionManifest`

## References

- `docs/foundation/ADR/003-static-analysis.md` — Why static analysis
- `docs/foundation/ADR/004-fail-fast.md` — Why circular imports are caught early
- `docs/protocols/manifest-schema.md` — Manifest specification
