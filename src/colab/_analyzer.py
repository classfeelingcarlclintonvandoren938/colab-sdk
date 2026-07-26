"""Static dependency analysis for Colab Client.

Produces an ``ExecutionManifest`` listing all required local files and
external packages by parsing Python source files via AST and resolving
imports recursively.
"""

import ast
import importlib.util
import sys
from pathlib import Path

from colab._exceptions import AnalysisError
from colab._manifest import ExecutionManifest

# Standard library module names — never packaged as project files.
_STDLIB_MODULES: frozenset[str] = frozenset({
    "abc", "ast", "asyncio", "base64", "binascii", "bisect", "builtins",
    "bz2", "calendar", "collections", "copy", "csv", "dataclasses",
    "datetime", "decimal", "difflib", "dis", "enum", "functools",
    "glob", "gzip", "hashlib", "html", "http", "importlib", "inspect",
    "io", "itertools", "json", "logging", "lzma", "math", "mmap",
    "multiprocessing", "operator", "os", "pathlib", "pickle", "platform",
    "pprint", "queue", "random", "re", "secrets", "shutil", "signal",
    "socket", "sqlite3", "ssl", "statistics", "string", "struct",
    "subprocess", "sys", "tarfile", "tempfile", "textwrap", "threading",
    "time", "timeit", "traceback", "tracemalloc", "types", "typing",
    "unittest", "urllib", "uuid", "warnings", "weakref", "xml",
    "xmlrpc", "zipfile", "zipimport", "zlib", "zoneinfo",
})


class Analyzer:
    """Resolves local imports for a given function via AST analysis.

    Produces an ``ExecutionManifest`` listing all required local files and
    external packages. Does **not** package or upload anything.

    Usage::

        analyzer = Analyzer(project_root=Path("."))
        manifest = analyzer.analyze("train", Path("app.py"))
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the analyzer with the project root directory.

        Args:
            project_root: Absolute or relative path to the project root.
        """
        self._root = project_root.resolve()
        self._visited: set[Path] = set()
        self._warnings: list[str] = []
        # Track module names confirmed as external during resolution
        # so _extract_packages does not re-run find_spec.
        self._external_imports: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, function_name: str, source_file: Path) -> ExecutionManifest:
        """Resolve all local imports reachable from the given source file.

        Args:
            function_name: Name of the target function (e.g. ``\"train\"``).
            source_file: Path to the ``.py`` file containing the function.

        Returns:
            An ``ExecutionManifest`` describing every file and package
            required to execute the function remotely.

        Raises:
            AnalysisError: If the source file does not exist, is not a
                ``.py`` file, or a local import cannot be resolved.
        """
        self._visited.clear()
        self._warnings.clear()
        self._external_imports.clear()

        # Temporarily add the project root to sys.path so that
        # importlib.util.find_spec() can resolve local modules even
        # in src/ layout projects. Restore on exit.
        root_str = str(self._root)
        added = root_str not in sys.path
        if added:
            sys.path.insert(0, root_str)

        try:
            source = source_file.resolve()

            if not source.exists():
                raise AnalysisError(f"Source file not found: {source}")
            if source.suffix != ".py":
                raise AnalysisError(f"Expected a .py file, got: {source}")

            files = self._resolve_recursive(source)
            requirements = sorted(self._external_imports)
        finally:
            if added:
                sys.path.remove(root_str)

        return ExecutionManifest(
            function_name=function_name,
            entry_point=_relpath(source, self._root),
            files=sorted(set(files)),
            requirements=sorted(requirements),
            warnings=list(self._warnings),
        )

    # ------------------------------------------------------------------
    # Import resolution (recursive DFS)
    # ------------------------------------------------------------------

    def _resolve_recursive(self, file: Path) -> list[Path]:
        """Walk imports recursively, collecting local source files.

        Uses a ``_visited`` set to avoid re-analysing files (handles
        circular dependencies gracefully).
        """
        if file in self._visited:
            return []
        self._visited.add(file)

        imports = _parse_imports(file)

        collected: list[Path] = [file]

        # --- Relative imports -------------------------------------------
        for module in imports["relative"]:
            resolved = _resolve_relative_import(module, file)
            if resolved is not None:
                collected.extend(self._resolve_recursive(resolved))

        # --- Absolute imports (local or external) -----------------------
        for module in imports["absolute"]:
            resolved = self._resolve_absolute_local(module)
            if resolved is not None:
                collected.extend(self._resolve_recursive(resolved))
            else:
                top = module.split(".", 1)[0]
                if top not in _STDLIB_MODULES:
                    self._external_imports.add(top)

        # --- Wildcard imports -------------------------------------------
        for module in imports["wildcard"]:
            resolved = self._resolve_package_dir(module)
            if resolved is None:
                top = module.split(".", 1)[0]
                if top not in _STDLIB_MODULES:
                    self._external_imports.add(top)
                continue

            if resolved.name == "__init__.py":
                # Package — include all .py files in the package tree
                pkg_dir = resolved.parent
                for py_file in sorted(pkg_dir.rglob("*.py")):
                    if py_file not in self._visited:
                        self._visited.add(py_file)
                        collected.append(py_file)
                        collected.extend(self._resolve_recursive(py_file))
            else:
                # Single-file module — just include the module itself
                if resolved not in self._visited:
                    self._visited.add(resolved)
                    collected.append(resolved)
                    collected.extend(self._resolve_recursive(resolved))

            self._warnings.append(
                f"Wildcard import from {module} in {_relpath(file, self._root)}"
            )

        # --- Dynamic import detection (warning only) --------------------
        for module in imports["dynamic"]:
            self._warnings.append(
                f"Dynamic import ({module}) in {_relpath(file, self._root)} "
                f"— cannot resolve statically"
            )

        return collected

    def _resolve_absolute_local(self, module: str) -> Path | None:
        """Resolve an absolute module name to a local file path.

        Returns ``None`` if the module is external (stdlib / site-packages)
        or cannot be found.
        """
        # Fast path: known stdlib module → definitely external
        top = module.split(".", 1)[0]
        if top in _STDLIB_MODULES:
            return None

        try:
            spec = importlib.util.find_spec(module)
        except (ModuleNotFoundError, ValueError):
            return None

        if spec is None:
            return None

        # Namespace packages have no origin → warn and skip
        if spec.origin is None:
            self._warnings.append(
                f"Namespace package '{module}' — include manually if needed"
            )
            return None

        origin = Path(spec.origin).resolve()
        if _is_relative_to(origin, self._root):
            return origin

        return None

    def _resolve_package_dir(self, module: str) -> Path | None:
        """Resolve a module to a file for wildcard import expansion.

        Returns ``None`` if the module is external or cannot be found.
        Returns the ``__init__.py`` path for packages, or the module's
        own ``.py`` path for single-file modules.
        """
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            return None

        origin = Path(spec.origin).resolve()
        if not _is_relative_to(origin, self._root):
            return None

        return origin

# ======================================================================
# Module-level helpers
# ======================================================================


def _parse_imports(file: Path) -> dict[str, list[str]]:
    """Parse a source file and return categorised import names.

    Returns a dict with keys ``\"relative\"``, ``\"absolute\"``,
    ``\"wildcard\"``, and ``\"dynamic\"``, each containing a list of
    module name strings.
    """
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except SyntaxError as e:
        raise AnalysisError(f"Syntax error in {file}: {e}") from e

    relative: list[str] = []
    absolute: list[str] = []
    wildcard: list[str] = []
    dynamic: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("."):
                    relative.append(alias.name)
                else:
                    absolute.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.module.startswith("."):
                relative.append(node.module)
            elif any(a.name == "*" for a in node.names):
                wildcard.append(node.module)
            else:
                absolute.append(node.module)

    # Detect dynamic imports: calls to import_module, __import__
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _get_call_name(node)
            if fn in ("importlib.import_module", "__import__"):
                if node.args:
                    arg = _try_extract_string(node.args[0])
                    if arg:
                        dynamic.append(arg)

    return {
        "relative": relative,
        "absolute": absolute,
        "wildcard": wildcard,
        "dynamic": dynamic,
    }


def _resolve_relative_import(module: str, current_file: Path) -> Path | None:
    """Resolve a relative import to an absolute file path.

    Handles ``.``, ``..``, ``.module``, ``..module.pkg`` style imports.
    Returns ``None`` if the module cannot be resolved.
    """
    parts = module.split(".")
    dots = len(parts[0])
    tail = parts[1:]  # e.g. ``[\"utils\", \"model\"]`` for ``..utils.model``

    # Start from the directory containing the current file
    origin = current_file.resolve().parent

    # Walk up ``dots - 1`` levels.  (One dot = same package, two dots =
    # parent package, etc.)
    for _ in range(dots - 1):
        origin = origin.parent

    if tail:
        # e.g. ``.utils.model`` → ``<origin>/utils/model``
        relative_path = origin.joinpath(*tail)
    else:
        # e.g. ``.`` → ``<origin>/__init__``
        relative_path = origin / "__init__"

    # Try ``.py`` extension
    py_path = relative_path.with_suffix(".py")
    if py_path.exists():
        return py_path

    # Try package (``__init__.py``)
    init_path = relative_path / "__init__.py"
    if init_path.exists():
        return init_path

    return None


def _get_call_name(node: ast.Call) -> str:
    """Extract the full dotted name of a call expression.

    Handles ``importlib.import_module(...)`` → ``\"importlib.import_module\"``
    and ``__import__(...)`` → ``\"__import__\"``.
    """
    if isinstance(node.func, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _try_extract_string(node: ast.AST) -> str | None:
    """Try to extract a string constant from an AST node.

    Returns ``None`` if the expression is not a constant string
    (e.g. a variable reference that cannot be statically resolved).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Check if *path* is strictly under *parent*.

    Compatible with Python 3.9+ (avoids ``Path.relative_to`` with
    a second argument which was added in 3.12).
    """
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _relpath(path: Path, base: Path) -> Path:
    """Return *path* relative to *base* if possible, else *path*."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path
