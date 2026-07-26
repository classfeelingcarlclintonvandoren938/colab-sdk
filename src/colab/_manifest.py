"""ExecutionManifest — data contract between Analyzer and Packager."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExecutionManifest:
    """Describes exactly what is needed to execute a single function remotely.

    Produced by the Analyzer and consumed by the Packager.
    Once created, the manifest is immutable — the same manifest always
    produces the same artifact.
    """

    function_name: str
    """Name of the function to execute (e.g. ``\"train\"``)."""

    entry_point: Path
    """Relative path to the source file containing the function."""

    files: list[Path] = field(default_factory=list)
    """All local source files required for execution.

    Paths are relative to the project root. Includes the entry point and
    all transitively imported local modules.
    """

    requirements: list[str] = field(default_factory=list)
    """External package names (PyPI).

    These are installed via ``pip`` on the VM, not uploaded.
    """

    requirements_hash: str = ""
    """Hex-encoded SHA256 digest of the sorted, joined requirements list.

    Used to skip re-installation of packages when the hash matches
    the cache on the VM.
    """

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings produced during analysis.

    Examples: wildcard imports, dynamic imports that could not be resolved.
    """

    def __post_init__(self) -> None:
        """Compute the requirements hash automatically if not provided."""
        if not self.requirements_hash and self.requirements:
            sorted_reqs = sorted(self.requirements)
            joined = "".join(sorted_reqs)
            hash_value = hashlib.sha256(joined.encode("utf-8")).hexdigest()
            # Use object.__setattr__ to work around frozen=True
            object.__setattr__(self, "requirements_hash", hash_value)

    @property
    def files_count(self) -> int:
        """Number of local source files in the manifest."""
        return len(self.files)

    @property
    def requirements_count(self) -> int:
        """Number of external packages in the manifest."""
        return len(self.requirements)
