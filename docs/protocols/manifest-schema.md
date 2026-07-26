# Manifest Schema

> The `ExecutionManifest` is the output of the Analyzer and the input to the Packager. It describes exactly what is needed to execute a single function remotely.

---

## Produced By

`Analyzer.analyze(function)`

## Consumed By

`Packager.build(manifest)`

---

## Schema

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class ExecutionManifest:
    """Data contract between Analyzer and Packager."""
    function_name: str
    entry_point: Path              # Path to the source file containing the function
    files: list[Path]              # Relative paths of all required local modules
    requirements: list[str]        # External package names (e.g., ["torch", "numpy"])
    requirements_hash: str         # SHA256 of sorted requirements list
    warnings: list[str] = field(default_factory=list)  # Non-fatal analysis warnings
```

### Fields

| Field | Type | Description |
|---|---|---|
| `function_name` | `str` | Name of the function to execute (e.g., `"train"`) |
| `entry_point` | `Path` | Relative path to the source file containing the function (e.g., `Path("app.py")`) |
| `files` | `list[Path]` | All local source files required for execution. Paths are relative to the project root. Includes the entry point, all transitively imported local modules, and any assets explicitly required. |
| `requirements` | `list[str]` | External package names (PyPI or conda). These are NOT uploaded — they are installed via `pip` on the VM. Versions should be pinned when known by the Analyzer. |
| `requirements_hash` | `str` | Hex-encoded SHA256 digest of the sorted, joined requirements list. Used by the Session component to skip re-installation of packages when the hash matches the cache on the VM. |
| `warnings` | `list[str]` | Non-fatal warnings produced during analysis (wildcard imports, dynamic imports, etc.). The Packager preserves these for logging. |

### Immutability

`ExecutionManifest` is frozen (immutable). Once produced by the Analyzer, it must not be modified. This guarantees deterministic packaging: the same manifest always produces the same artifact.

---

## JSON Representation

When serialized (e.g., for logging or caching):

```json
{
    "function_name": "train",
    "entry_point": "app.py",
    "files": [
        "app.py",
        "training/trainer.py",
        "utils/model.py",
        "config.py"
    ],
    "requirements": [
        "numpy",
        "torch"
    ],
    "requirements_hash": "a83bf9e2d1c4...",
    "warnings": [
        "Wildcard import at app.py:5: from utils import *"
    ]
}
```

---

## Versioning

The schema version is implicit in the `frozen` dataclass. Any change to the schema (adding a field, changing a type) is a breaking change and must be coordinated between Analyzer and Packager.

Future migrations should maintain backward compatibility for at least one release cycle.
