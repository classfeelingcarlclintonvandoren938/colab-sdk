#!/usr/bin/env python3
"""
Colab SDK — Integration Test (manual)

Run this script from WSL2 (or any Linux/macOS) with a working
``google-colab-cli`` installation.  It exercises the full SDK pipeline:

    1. Session creation (``colab new``)
    2. Static analysis (AST import resolution)
    3. Remote execution + result parsing
    4. Session reuse on consecutive calls

Prerequisites:
    - ``colab-sdk`` installed (``pip install -e .``)
    - ``google-colab-cli`` installed (``pip install google-colab-cli``)
    - Authenticated (``uv tool install google-colab-cli --with jupyter-kernel-client==0.9.0``)

Usage:
    cd /path/to/colab-sdk
    python examples/integration_test.py
"""

# ---------------------------------------------------------------------------
# Pure functions — defined at module level so the Colab VM can import them
# without any SDK dependency.  These are the functions executed remotely.
# ---------------------------------------------------------------------------


def hello() -> str:
    """Simple function returning a greeting."""
    return "Hello from Colab!"


def add(a: int, b: int) -> int:
    """Function with positional arguments."""
    return a + b


def train(epochs: int = 10, lr: float = 0.01) -> dict:
    """Function with kwargs, returning a dict."""
    import time as _time
    _time.sleep(0.5)  # simulate a tiny bit of work
    return {"done": True, "epochs": epochs, "lr": lr}


# ---------------------------------------------------------------------------
# Local-only: SDK imports and test orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    import time
    import uuid
    from pathlib import Path

    # Ensure the SDK is importable from the local source tree
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

    from colab import App

    print("=" * 60)
    print("Colab Client — Integration Test")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Create App (CPU — no GPU cost, faster startup)
    # ------------------------------------------------------------------
    print("\n[1/7] Creating App (CPU session)...")
    app = App(gpu=None, session_name=f"colab-test-{uuid.uuid4().hex[:6]}")
    print(f"      Session name: {app.session_name}")
    print(f"      GPU:          {app.gpu or '(CPU)'}")
    print("      ✓ OK")

    # ------------------------------------------------------------------
    # 2. Register pre-defined functions
    # ------------------------------------------------------------------
    print("\n[2/7] Registering functions with @app.function...")
    # Must assign the return value — app.function returns a RemoteFunction,
    # replacing the original function.  Use distinct names to avoid
    # ``UnboundLocalError`` (``hello = app.function(hello)`` would make
    # Python treat ``hello`` as a local throughout the function).
    hello_fn = app.function(hello)
    add_fn = app.function(add)
    train_fn = app.function(train)
    print("      Registered: hello, add, train")
    print("      ✓ OK")

    # ------------------------------------------------------------------
    # 3. Set a secret
    # ------------------------------------------------------------------
    print("\n[3/7] Setting a secret...")
    app.secret("MY_SECRET", "s3kr3t-value")
    print(f"      secrets: {app.secrets}")
    print("      ✓ OK")

    # ------------------------------------------------------------------
    # Execute tests with guaranteed cleanup
    # ------------------------------------------------------------------
    try:
        # --- 4. First call (triggers VM provisioning) ---
        print("\n[4/7] Executing hello_fn.remote() (first call — VM boots)...")
        print("      (This may take 20-30 seconds for VM provisioning)")
        t0 = time.time()
        result = hello_fn.remote(debug=True)
        elapsed = time.time() - t0
        print(f"      Result: {result!r}")
        print(f"      Time:   {elapsed:.1f}s")
        assert result == "Hello from Colab!", f"Unexpected result: {result}"
        print("      ✓ PASS")

        # --- 5. Session reuse (faster) ---
        print("\n[5/7] Executing add_fn.remote(40, 2) (session reuse)...")
        t0 = time.time()
        result = add_fn.remote(40, 2)
        elapsed = time.time() - t0
        print(f"      Result: {result!r}")
        print(f"      Time:   {elapsed:.1f}s")
        assert result == 42, f"Unexpected result: {result}"
        print("      ✓ PASS")

        # --- 6. Dict return + kwargs ---
        print("\n[6/7] Executing train_fn.remote(epochs=5, lr=0.001)...")
        t0 = time.time()
        result = train_fn.remote(epochs=5, lr=0.001)
        elapsed = time.time() - t0
        print(f"      Result: {result!r}")
        print(f"      Time:   {elapsed:.1f}s")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result["done"] is True
        assert result["epochs"] == 5
        assert result["lr"] == 0.001
        print("      ✓ PASS")

    except Exception as e:
        print(f"\n      ✗ FAIL: {e}")
        sys.exit(1)

    finally:
        # --- 7. Always clean up ---
        print("\n[7/7] Shutting down session (cleanup)...")
        app.shutdown()
        print("      ✓ OK")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("ALL INTEGRATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
