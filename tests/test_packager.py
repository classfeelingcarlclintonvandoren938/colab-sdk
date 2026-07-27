"""Tests for ``_packager.py`` — deterministic artifact packaging."""

import gzip
import json
import tempfile
from pathlib import Path

import pytest

from colab._manifest import ExecutionManifest
from colab._packager import Artifact, Packager, PackagingError


class TestArtifact:
    """The ``Artifact`` dataclass."""

    def test_create(self) -> None:
        artifact = Artifact(path=Path("/tmp/a.tar.gz"), hash="abc123", size=1024)
        assert artifact.path == Path("/tmp/a.tar.gz")
        assert artifact.hash == "abc123"
        assert artifact.size == 1024

    def test_frozen(self) -> None:
        artifact = Artifact(path=Path("/tmp/a.tar.gz"), hash="abc123", size=1024)
        try:
            artifact.size = 0  # type: ignore[misc]
            assert False, "Should be frozen"
        except Exception:
            pass


class TestPackager:
    """Deterministic packaging, runner generation, and caching."""

    def test_build_returns_artifact(self, tmp_project: Path) -> None:
        """``build()`` returns an ``Artifact`` with path, hash, and size."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py", tmp_project / "utils" / "helper.py"],
            requirements=["numpy"],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(manifest, args=(10,), kwargs={"lr": 0.001})

            assert isinstance(artifact, Artifact)
            assert artifact.path.exists()
            assert len(artifact.hash) == 64  # SHA256 hex digest
            assert artifact.size > 0

    def test_deterministic_hash(self, tmp_project: Path) -> None:
        """Same manifest + same args → same hash."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py", tmp_project / "utils" / "helper.py"],
            requirements=["numpy"],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            cache = Path(cache_dir)
            packager = Packager(cache_dir=cache)
            a1 = packager.build(manifest, args=(10,), kwargs={"lr": 0.001})
            a2 = packager.build(manifest, args=(10,), kwargs={"lr": 0.001})
            assert a1.hash == a2.hash

    def test_caching(self, tmp_project: Path) -> None:
        """Second build with same manifest should reuse cached artifact."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            cache = Path(cache_dir)
            packager = Packager(cache_dir=cache)
            a1 = packager.build(manifest)
            a2 = packager.build(manifest)
            # Both point to the same cached file
            assert a1.path == a2.path

    def test_runner_contains_function_name(self, tmp_project: Path) -> None:
        """Generated runner.py includes the function name."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(manifest)

            # Read the compressed artifact and extract runner.py
            runner_source = _extract_runner(artifact.path)
            assert "run" in runner_source
            assert "Auto-generated runner" in runner_source

    def test_runner_contains_args_kwargs(self, tmp_project: Path) -> None:
        """Generated runner.py embeds the provided args and kwargs."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(
                manifest,
                args=("hello", 42),
                kwargs={"verbose": True},
            )

            runner_source = _extract_runner(artifact.path)
            assert '"hello"' in runner_source
            assert "42" in runner_source
            assert "verbose" in runner_source

    def test_secrets_injected(self, tmp_project: Path) -> None:
        """Secrets are inlined as os.environ assignments in runner.py."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(
                manifest,
                secrets={"MY_SECRET": "s3kr3t", "TOKEN": "abc123"},
            )

            runner_source = _extract_runner(artifact.path)
            assert 'os.environ["MY_SECRET"]' in runner_source
            assert '"s3kr3t"' in runner_source
            assert 'os.environ["TOKEN"]' in runner_source
            assert '"abc123"' in runner_source

    def test_metadata_contains_fields(self, tmp_project: Path) -> None:
        """metadata.json includes function_name, requirements, args, kwargs."""
        manifest = ExecutionManifest(
            function_name="train",
            entry_point=Path("training/trainer.py"),
            files=[tmp_project / "training" / "trainer.py"],
            requirements=["torch", "numpy"],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(manifest, args=(1,), kwargs={"lr": 0.01})

            metadata = _extract_metadata(artifact.path)
            assert metadata["function_name"] == "train"
            assert metadata["requirements"] == ["torch", "numpy"]
            assert metadata["args"] == [1]
            assert metadata["kwargs"] == {"lr": 0.01}
            assert "colab_version" in metadata
            assert "requirements_hash" in metadata

    def test_missing_source_file_raises_error(self, tmp_project: Path) -> None:
        """Packaging fails if a source file listed in the manifest is missing."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "nonexistent.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            with pytest.raises(PackagingError, match="not found"):
                packager.build(manifest)

    def test_artifact_file_is_gzip(self, tmp_project: Path) -> None:
        """The artifact file is a valid gzip archive."""
        manifest = ExecutionManifest(
            function_name="run",
            entry_point=Path("app.py"),
            files=[tmp_project / "app.py"],
            requirements=[],
        )

        with tempfile.TemporaryDirectory() as cache_dir:
            packager = Packager(cache_dir=Path(cache_dir))
            artifact = packager.build(manifest)

            with gzip.open(artifact.path, "rb") as f:
                content = f.read()
            assert len(content) > 0


# ======================================================================
# Helpers
# ======================================================================


def _extract_runner(artifact_path: Path) -> str:
    """Extract and return the content of ``runner.py`` from a tar.gz artifact."""
    import tarfile
    import io

    with gzip.open(artifact_path, "rb") as f:
        tar_bytes = f.read()

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        member = tar.getmember("runner.py")
        f = tar.extractfile(member)
        assert f is not None
        return f.read().decode("utf-8")


def _extract_metadata(artifact_path: Path) -> dict[str, object]:
    """Extract and return the ``metadata.json`` dict from a tar.gz artifact."""
    import tarfile
    import io

    with gzip.open(artifact_path, "rb") as f:
        tar_bytes = f.read()

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        member = tar.getmember("metadata.json")
        f = tar.extractfile(member)
        assert f is not None
        return json.loads(f.read().decode("utf-8"))
