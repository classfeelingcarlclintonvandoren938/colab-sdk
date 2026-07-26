# Execution Engine — ADR

> Component-specific decisions for the Execution Engine.

---

## Why Engine only orchestrates

The Engine's sole responsibility is calling other components in the correct order. It does not implement analysis, packaging, or network logic.

If the Engine also handled packaging, changing the packaging strategy would require changing the Engine. By keeping it as an orchestrator, each component can evolve independently.

## Why retry only for session death

Session death is the only transient failure that retry can fix. If the Colab VM dies (idle timeout, network loss), creating a new session and re-executing is the correct recovery.

Other failures are not transient:
- Invalid configuration → must be fixed by the user
- Function exception → re-executing will produce the same exception
- Auth failure → must be fixed by the user

## Why no progress tracking in the Engine

Progress tracking (`__LAZY_PROGRESS__`) is a protocol-level concern. The Engine parses it from stdout but does not aggregate or persist it. Progress is forwarded to the caller in real-time.

## References

- ADR-004 (Fail Fast)
- `docs/protocols/stdout-protocol.md` — Result and error parsing
