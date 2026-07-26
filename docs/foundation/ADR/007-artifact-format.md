# ADR-007: Artifact Format (tar.gz)

**Status:** Accepted

---

## Context

After the Analyzer produces an `ExecutionManifest`, the Packager must transform it into a deployable unit that can be transferred to and executed on the Colab VM.

Several formats were considered:
1. **Single `.py` file (inline)** — Bundle all source code into one Python file using string concatenation or custom bundling.
2. **`.tar.gz` archive** — Standard Unix archive format, preserve directory structure.
3. **Individual file upload** — Upload each file separately via `colab upload`.
4. **ZIP archive** — Alternative compressed format.

## Decision

Use **`.tar.gz` archive** with a deterministic directory structure. The archive is produced by the Packager and transferred to the Colab VM via `colab upload`.

```
artifact.tar.gz
  └── <session>/<artifact_hash>/
      ├── runner.py           # Generated entry point
      ├── metadata.json       # Execution metadata
      └── files/
          ├── training/
          │   └── trainer.py  # Analyzed source files
          ├── utils/
          │   └── model.py
          └── config.py
```

## Rationale

- **Preserves directory structure**: Source files maintain their original relative paths. Stack traces show correct file paths. Imports work without modification.
- **Standard format**: `.tar.gz` is universally supported on Linux and macOS. The Colab VM can extract it with standard library tools (`tar`).
- **Deterministic**: Given the same manifest and source files, the same bytes are produced. Enables caching by hash.
- **Extract once, execute many**: With a persistent session, the artifact is extracted once and cached on the VM. Subsequent calls skip upload and extraction if the hash matches.
- **Clean boundary**: The artifact is a self-contained unit. It has no external dependencies on the user's project structure.

## Trade-offs

- **Overhead for trivial functions**: A single "Hello World" function still creates a `.tar.gz` with a directory structure, `runner.py`, and metadata. However, this overhead is negligible (a few hundred bytes).
- **Extraction step**: The VM must extract the archive before execution. This adds ~100-200ms. Inline source would skip this step.

## Consequences

- The Packager produces `.tar.gz` files, not `.py` files or ZIP archives.
- The artifact has a fixed directory structure.
- `runner.py` is the entry point. It imports the target function from the `files/` subtree and handles result serialization.
- `metadata.json` contains: manifest hash, requirements hash, function name, GPU type, timestamp.
- The artifact hash is computed from the deterministic `.tar.gz` bytes for caching.

## Alternatives Considered

**Single `.py` file (inline source).** Rejected because:
- Inlining source breaks stack traces (every line maps to line 1 of an enormous file).
- Relative imports break when files are concatenated out of their package context.
- Debugging becomes impossible — you can't open `utils/model.py` because it doesn't exist on disk.
- This is the approach we explicitly decided not to use.

**Individual file upload.** Rejected because:
- `colab upload` per file creates many round-trips.
- No atomic deployment: if upload 5 of 10 files fails, the VM is in an inconsistent state.
- No caching: can't hash the whole deployment, only individual files.

**ZIP archive.** Rejected because `.tar.gz` is more standard on Linux (Colab VM environment) and supports Unix file permissions.

## References

- CONSTITUTION.md, Rule 9 (Deterministic Artifacts)
- `docs/protocols/artifact-format.md` (detailed spec)
- `docs/components/packager/SPEC.md`
