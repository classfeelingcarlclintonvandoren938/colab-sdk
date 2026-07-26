# Packager — ADR

> Component-specific decisions for the Packager.

---

## Why generate runner.py instead of modifying the original function

Modifying the user's source code would be fragile and invasive. Generating a standalone `runner.py` keeps a clean boundary between user code and framework code. The user's files are copied verbatim, and the framework's entry point is a separate file.

## Why args/kwargs are embedded in runner.py

Arguments are serialized as JSON and embedded directly in `runner.py`. This avoids a separate upload step for execution parameters. The limitation is that only JSON-serializable arguments are supported (strings, numbers, booleans, lists, dicts, None).

## Why strip file metadata from the archive

File permissions, timestamps, and owner metadata vary across platforms and users. Including them would make the artifact non-deterministic: the same source files on different machines would produce different archives. Stripping metadata ensures deterministic builds.

## Why no verification step

The Packager could verify that all files in the manifest are present before building. However, this is the Analyzer's responsibility: if a file is in the manifest, it was already confirmed to exist during analysis. Checking again would duplicate validation (violating the fail-fast principle differently — fail once, fail correctly).

## References

- `components/packager/SPEC.md` — Full specification
- `docs/foundation/ADR/007-artifact-format.md` — Why `.tar.gz`
