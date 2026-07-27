# Packager — SPEC

> Consumes an `ExecutionManifest` and produces a deterministic `.tar.gz` artifact.

---

## Input

`packager.build(manifest: ExecutionManifest, args: tuple, kwargs: dict, secrets: dict[str, str] | None = None) -> Artifact`

Where `Artifact` is:

```python
@dataclass(frozen=True)
class Artifact:
    path: Path           # Path to the .tar.gz file on disk
    hash: str            # SHA256 hex digest of the uncompressed content
    size: int            # Size in bytes of the .tar.gz file
```

## Output

A `.tar.gz` file on disk at a deterministic location. See `protocols/artifact-format.md` for the full structure.

## Pipeline

```
build(manifest, args, kwargs)
  │
  ├── 1. Create staging directory
  │     <cache>/<artifact_hash>/
  │
  ├── 2. Copy source files
  │     Copy each file from manifest.files into staging/files/
  │     Preserve relative directory structure
  │
  ├── 3. Inject secrets into runner.py preamble
  │     For each key/value in secrets dict:
  │       Add `os.environ["<key>"] = "<value>"` at the top of runner.py
  │     (before function import — secrets are available before the target function runs)
  │
  ├── 4. Generate metadata.json
  │     function_name, requirements_hash, requirements, gpu, args, kwargs
  │     (No timestamp — metadata must be deterministic for artifact hash stability)
  │
  ├── 5. Generate runner.py
  │     Entry point script with:
  │       - sys.path setup for files/
  │       - Secret env var injection (from step 3)
  │       - Function import and execution
  │       - Result serialization via __LAZY_RESULT__
  │       - Error handling via __LAZY_ERROR__
  │
  ├── 6. Create tar.gz
  │     Compress staging directory
  │     Omit: file permissions, timestamps, owner info (for determinism)
  │
  └── 7. Return Artifact(path, hash, size)
```

## runner.py Generation

The `runner.py` is the most critical output. It must:

1. Add the `files/` directory to `sys.path`
2. Install required packages (if not already installed based on hash)
3. Import the target function by its fully qualified name
4. Call it with the provided `args` and `kwargs`
5. Serialize the result via `__LAZY_RESULT__:...`
6. Catch exceptions and emit `__LAZY_ERROR__:...`

```python
# Auto-generated runner.py
import json, sys, traceback
from pathlib import Path

FILES_DIR = Path(__file__).parent / "files"
sys.path.insert(0, str(FILES_DIR))

def emit_result(value):
    print(f"__LAZY_RESULT__:{json.dumps({'status': 'ok', 'value': value})}", flush=True)

def emit_error(exc):
    tb = traceback.format_exc().splitlines(keepends=True)
    print(f"__LAZY_ERROR__:{json.dumps({'status': 'error', 'type': type(exc).__name__, 'message': str(exc), 'traceback': tb})}", file=sys.stderr, flush=True)

from training.trainer import train
try:
    result = train(epochs=10, lr=0.001)
    emit_result(result)
except Exception as e:
    emit_error(e)
    sys.exit(1)
```

## Determinism

The `.tar.gz` is built deterministically:
- Files are added in alphabetical order by path
- Timestamps, permissions, and owner metadata are stripped
- The hash is computed from the uncompressed byte stream before gzip compression

This ensures: same manifest + same source files = same artifact hash.

## Edge Cases

- **Empty manifest**: If a function has no local dependencies (only external packages), `files/` contains only the entry point.
- **Binary files**: Analyzed `.so`, `.pyd`, or other binary files are copied verbatim.
- **Large files**: No size limit is enforced by the Packager. Very large files may cause slow uploads (a Colab VM concern, not a packaging concern).
- **Special characters**: File paths with special characters are handled by `tarfile`'s standard handling.

## What Packager Does NOT Do

- Analyze code
- Upload artifacts
- Execute code
- Resolve dependencies

## Protocol Dependencies

- `protocols/manifest-schema.md` — Consumes `ExecutionManifest`
- `protocols/stdout-protocol.md` — Generates `runner.py` that produces `__LAZY_*` output
- `protocols/artifact-format.md` — Produces `.tar.gz` in the defined structure

## References

- `docs/foundation/ADR/007-artifact-format.md` — Why `.tar.gz`
- `docs/protocols/artifact-format.md` — Detailed artifact structure
