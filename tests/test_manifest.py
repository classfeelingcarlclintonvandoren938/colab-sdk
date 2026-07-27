"""Tests for ``_manifest.py`` — ``ExecutionManifest`` dataclass."""

import hashlib
from pathlib import Path

from colab._manifest import ExecutionManifest


class TestExecutionManifest:
    """Cover creation, immutability, hash computation, and properties."""

    def test_create_minimal(self) -> None:
        """A manifest can be created with only required fields."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
        )
        assert manifest.function_name == "train"
        assert manifest.entry_point == Path("app.py")
        assert manifest.files == []
        assert manifest.requirements == []
        assert manifest.requirements_hash == ""
        assert manifest.warnings == []

    def test_create_full(self) -> None:
        """A manifest with all fields is stored correctly."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            files=[Path("app.py"), Path("utils/helper.py")],
            requirements=["torch", "numpy"],
            warnings=["Wildcard import"],
        )
        assert manifest.function_name == "train"
        assert len(manifest.files) == 2
        assert len(manifest.requirements) == 2
        assert len(manifest.warnings) == 1

    def test_frozen_immutable(self) -> None:
        """ExecutionManifest is frozen — attempting mutation raises."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
        )
        try:
            manifest.function_name = "predict"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except Exception:
            pass  # Expected — dataclass is frozen

    def test_requirements_hash_computed(self) -> None:
        """SHA256 hash is auto-computed from sorted requirements."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            requirements=["numpy", "torch"],
        )
        expected_hash = hashlib.sha256(b"numpytorch").hexdigest()
        assert manifest.requirements_hash == expected_hash

    def test_requirements_hash_empty(self) -> None:
        """No hash is computed when requirements list is empty."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
        )
        assert manifest.requirements_hash == ""

    def test_requirements_hash_deterministic(self) -> None:
        """Same requirements (different order) produce the same hash."""
        m1 = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            requirements=["torch", "numpy"],
        )
        m2 = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            requirements=["numpy", "torch"],
        )
        assert m1.requirements_hash == m2.requirements_hash

    def test_files_count_property(self) -> None:
        """``files_count`` returns the number of local files."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            files=[Path("a.py"), Path("b.py"), Path("c.py")],
        )
        assert manifest.files_count == 3

    def test_requirements_count_property(self) -> None:
        """``requirements_count`` returns the number of external packages."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("app.py"),
            requirements=["torch", "numpy", "pillow"],
        )
        assert manifest.requirements_count == 3
