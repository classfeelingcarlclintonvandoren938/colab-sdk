"""Tests for ``_analyzer.py`` — AST-based import resolution."""

from pathlib import Path

import pytest

from colab._analyzer import Analyzer
from colab._exceptions import AnalysisError


class TestAnalyzer:
    """Cover the full import-resolution pipeline."""

    # ------------------------------------------------------------------
    # Basic resolution
    # ------------------------------------------------------------------

    def test_resolves_local_imports(self, tmp_project: Path) -> None:
        """Local imports are resolved and included in the manifest."""
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("run", tmp_project / "app.py")

        assert manifest.function_name == "run"
        assert manifest.entry_point == Path("app.py")
        # app.py + utils/__init__ + utils/helper.py + training/__init__ + training/trainer.py
        assert len(manifest.files) >= 3

    def test_detects_external_packages(self, tmp_project: Path) -> None:
        """External (non-stdlib) imports appear in requirements."""
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("run", tmp_project / "app.py")

        # training/trainer.py imports torch; app.py imports numpy
        # (numpy: from app.py; torch: from training/trainer.py)
        assert "numpy" in manifest.requirements
        assert "torch" in manifest.requirements

    def test_stdlib_modules_excluded(self, tmp_project: Path) -> None:
        """stdlib imports should not appear in requirements."""
        # Create a file that imports stdlib only
        (tmp_project / "stdlib_test.py").write_text(
            "import os\nimport json\nfrom pathlib import Path\n"
        )
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "stdlib_test.py")
        # os, json, pathlib are all stdlib
        assert manifest.requirements == []

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_missing_source_file(self, tmp_project: Path) -> None:
        """Analyzing a non-existent file raises AnalysisError."""
        analyzer = Analyzer(project_root=tmp_project)
        with pytest.raises(AnalysisError, match="not found"):
            analyzer.analyze("foo", tmp_project / "nonexistent.py")

    def test_non_py_file(self, tmp_project: Path) -> None:
        """Analyzing a non-.py file raises AnalysisError."""
        (tmp_project / "data.txt").write_text("hello")
        analyzer = Analyzer(project_root=tmp_project)
        with pytest.raises(AnalysisError, match=".py"):
            analyzer.analyze("foo", tmp_project / "data.txt")

    def test_circular_dependency(self, tmp_project: Path) -> None:
        """Circular imports are handled without infinite recursion."""
        (tmp_project / "a.py").write_text("from b import bar\n")
        (tmp_project / "b.py").write_text("from a import foo\n")
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("foo", tmp_project / "a.py")
        # Both files should be in the manifest, no crash
        file_names = {f.name for f in manifest.files}
        assert "a.py" in file_names
        assert "b.py" in file_names

    def test_relative_import(self, tmp_project: Path) -> None:
        """Relative imports are resolved correctly."""
        (tmp_project / "pkg").mkdir()
        (tmp_project / "pkg" / "__init__.py").write_text("")
        (tmp_project / "pkg" / "mod.py").write_text(
            "from . import sibling\nVALUE = 1\n"
        )
        (tmp_project / "pkg" / "sibling.py").write_text(
            "from ..pkg.mod import VALUE\n"
        )

        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "pkg" / "mod.py")
        file_names = {str(f) for f in manifest.files}
        assert "pkg/mod.py" in file_names or any("mod.py" in f for f in file_names)

    def test_wildcard_import_warning(self, tmp_project: Path) -> None:
        """Wildcard imports from local packages produce a warning."""
        # Create a local package to wildcard-import
        (tmp_project / "mylib").mkdir()
        (tmp_project / "mylib" / "__init__.py").write_text("")
        (tmp_project / "mylib" / "stuff.py").write_text("X = 1\n")
        (tmp_project / "wild_test.py").write_text(
            "from mylib import *\n"
        )
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "wild_test.py")
        assert any("Wildcard" in w for w in manifest.warnings)

    def test_dynamic_import_warning(self, tmp_project: Path) -> None:
        """``importlib.import_module`` calls produce a warning."""
        (tmp_project / "dynamic_test.py").write_text(
            "import importlib\n"
            "mod = importlib.import_module('http.server')\n"
        )
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "dynamic_test.py")
        assert any("Dynamic" in w for w in manifest.warnings)

    def test_empty_file(self, tmp_project: Path) -> None:
        """An empty source file is handled without error."""
        (tmp_project / "empty.py").write_text("")
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "empty.py")
        assert manifest.files_count >= 1
        assert manifest.requirements == []

    def test_init_py_package(self, tmp_project: Path) -> None:
        """Importing a package (via __init__.py) works."""
        (tmp_project / "mypkg").mkdir()
        (tmp_project / "mypkg" / "__init__.py").write_text(
            "from . import sub\n"
        )
        (tmp_project / "mypkg" / "sub.py").write_text("X = 1\n")
        (tmp_project / "entry.py").write_text(
            "from mypkg import sub\n"
        )
        analyzer = Analyzer(project_root=tmp_project)
        manifest = analyzer.analyze("dummy", tmp_project / "entry.py")
        # Normalise to forward slashes for cross-platform comparison
        file_names = {
            Path(f).as_posix() for f in manifest.files
        }
        assert any("mypkg/__init__.py" in n for n in file_names)
        assert any("mypkg/sub.py" in n for n in file_names)
