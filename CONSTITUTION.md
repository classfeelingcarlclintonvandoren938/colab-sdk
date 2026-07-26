# Constitution — Colab Client

> Immutable project laws. Every contributor (human or AI) must follow these rules.

---

## 1. Single Identity

This project is **Colab Client**. It is a Python SDK for Google Colab.

There is no multi-provider abstraction. No `Provider`, `Runtime`, `ProviderInterface`, or similar speculative abstractions exist in the codebase. If a second runtime is ever supported, refactoring is accepted as a cost at that time.

## 2. Google Colab Only

The SDK targets **Google Colab exclusively**. All architectural decisions assume Colab as the runtime. Any code, comment, or documentation suggesting otherwise is automatically incorrect unless explicitly approved.

## 3. Official Integrations First

Whenever Google provides an official API or CLI for a needed capability, prefer it over reverse engineering, browser automation, or undocumented APIs. This project uses `google-colab-cli` as its backend — not Selenium, not cookie scraping, not internal API calls.

## 4. Fail Fast

Configuration errors must be detected before execution whenever possible. Validate at decoration time what can be validated at decoration time. Never let a misconfiguration silently propagate to a runtime failure.

## 5. Smart Client

All business logic lives in the SDK (the client). The Colab VM is treated as a stateless executor. The client analyzes, packages, uploads, and orchestrates. The VM only executes what it receives.

## 6. Lazy by Default

Do nothing until it must be done. Session creation is lazy (first `.remote()` triggers VM boot). Dependency analysis is lazy (only analyze what the function needs). Packaging is lazy (only package what the manifest includes).

## 7. Minimal Abstraction

Every abstraction must earn its existence. Do not introduce a base class, interface, or factory until there are at least three concrete implementations that justify it (Rule of Three). A single implementation does not justify an abstraction.

## 8. Locality Over Reusability

A component's documentation should be self-contained. An AI implementing the Analyzer should only need to read: foundation docs + protocols + the Analyzer SPEC + its ADRs. It should not need to read about the Session, the Packager, or the App.

## 9. Deterministic Artifacts

All build artifacts (manifests, packages, hashes) must be deterministic. Given the same input, the same output must be produced every time. This enables caching, reproducibility, and debuggability.

## 10. Explicit Lifecycle

Session creation and teardown must be explicit or timeout-based. No automatic shutdown on Python process exit. The user owns the session lifecycle. The SDK provides `app.shutdown()` for explicit control and idle timeout for automatic cleanup.

## 11. One App, One Session

A single `App` instance corresponds to exactly one persistent Colab session. Multiple `App` instances may exist, but each manages its own session independently.

## 12. Never Upload the Whole Project

Only analyzed, required files are packaged into the artifact. The framework never uploads source files that the target function does not transitively import. This is a hard invariant enforced by the Analyzer.

---

## Amendment Process

These rules can only be amended by:

1. Opening a GitHub Discussion with the proposed change
2. Achieving consensus among maintainers
3. Updating this file with rationale for the change

No single contributor (human or AI) may unilaterally override these rules.
