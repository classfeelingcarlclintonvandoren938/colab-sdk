#!/usr/bin/env python3
"""Smoke test for colab-sdk — verifies the published package works."""

import subprocess
import sys


def main() -> int:
    print("=" * 60)
    print("colab-sdk — PyPI Smoke Test")
    print("=" * 60)

    # 1. Show installed version
    print("\n[1/5] Checking installed version...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "colab-sdk"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("  ✗ colab-sdk is not installed!")
        print("  Run: pip install colab-sdk")
        return 1
    print(f"  {result.stdout}")
    print("  ✓ OK")

    # 2. Verify import works
    print("\n[2/5] Verifying import...")
    try:
        from colab import App, RemoteFunction
        from colab._exceptions import (
            AnalysisError, AuthError, ColabClientError,
            PackagingError, ProtocolError, RemoteExecutionError,
            SessionDeadError, SessionError, SessionGpuMismatchError,
            ValidationError,
        )
        from colab._protocol import LogMessage, ProgressMessage, ResultMessage
        print("  ✓ from colab import App, RemoteFunction")
        print("  ✓ All exceptions imported")
        print("  ✓ Protocol types imported")
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return 1

    # 3. Verify App construction
    print("\n[3/5] Testing App construction...")
    try:
        app = App(gpu=None)
        assert app.gpu is None
        assert app.session_name.startswith("colab-session-")
        assert app.secrets == {}
        print(f"  ✓ App() created")
        print(f"  ✓ session_name: {app.session_name}")
        print(f"  ✓ gpu: {app.gpu}")
        print(f"  ✓ secrets: {app.secrets}")
    except Exception as e:
        print(f"  ✗ App construction failed: {e}")
        return 1

    # 4. Verify App with GPU
    print("\n[4/5] Testing App with GPU...")
    try:
        app_gpu = App(gpu="T4", session_name="smoke-test-gpu")
        assert app_gpu.gpu == "T4"
        assert app_gpu.session_name == "smoke-test-gpu"
        print(f"  ✓ App(gpu='T4') created")
        print(f"  ✓ session_name: {app_gpu.session_name}")
    except Exception as e:
        print(f"  ✗ GPU App failed: {e}")
        return 1

    # 5. Verify function decorator + RemoteFunction
    print("\n[5/5] Testing @app.function decorator...")
    try:
        app2 = App()

        @app2.function
        def hello() -> str:
            return "Hello!"

        assert isinstance(hello, RemoteFunction)
        assert hello.name == "hello"
        assert hello.source_file.suffix == ".py"
        assert hello.source_file.exists()
        print(f"  ✓ @app.function decorated hello()")
        print(f"  ✓ RemoteFunction.name: {hello.name}")
        print(f"  ✓ RemoteFunction.source_file: {hello.source_file.name}")

        @app2.function(gpu="A100", timeout=600)
        def train() -> dict:
            return {"done": True}

        assert train.name == "train"
        assert train.gpu == "A100"
        assert train.timeout == 600
        print(f"  ✓ @app.function(gpu='A100', timeout=600) decorated train()")
        print(f"  ✓ RemoteFunction.gpu: {train.gpu}")
        print(f"  ✓ RemoteFunction.timeout: {train.timeout}")
    except Exception as e:
        print(f"  ✗ Decorator test failed: {e}")
        return 1

    # Summary
    print("\n" + "=" * 60)
    print("ALL SMOKE TESTS PASSED ✓")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
