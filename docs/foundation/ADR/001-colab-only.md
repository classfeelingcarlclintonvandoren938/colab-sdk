# ADR-001: Google Colab Only

**Status:** Accepted

---

## Context

The project needed to decide whether to design for multiple compute runtimes (Colab, Kaggle, HuggingFace, Docker) from the start, or to focus exclusively on Google Colab.

Early discussions considered a `Provider` abstraction that would allow plugging in different backends. However, no second provider had concrete requirements or a clear implementation path.

## Decision

The project targets **Google Colab exclusively** for v1. No `Provider` abstraction, no `Runtime` interface, no provider selection parameter exists in the codebase.

```python
# This is the API:
app = App()

# NOT this:
app = App(provider="colab")
```

## Rationale

- **Single identity**: The project is called Colab Client. It should be optimized for one platform, not generic for many.
- **Rule of Three**: No abstraction should exist before three concrete implementations justify it. There is exactly one runtime (Colab). An abstraction would be speculative.
- **Reduced complexity**: Every provider abstraction adds surface area: base classes, factory methods, configuration, documentation, testing matrices. All of this is eliminated.
- **Better product**: A focused product that does one thing well is more valuable than a generic product that does many things poorly.

## Trade-offs

- Adding a second runtime later will require introducing a provider abstraction at that time, which means refactoring.
- The refactoring cost is accepted as a deliberate trade-off. It is lower than the ongoing cost of maintaining unused abstractions.

## Consequences

- The `App` constructor does not accept a `provider` parameter.
- No `BaseProvider`, `ProviderInterface`, `Runtime`, or `RuntimeManager` classes exist in the codebase.
- All documentation, ADRs, and examples assume Google Colab.
- If a second runtime is ever added, the initial ADR for that effort must be: "Extract Provider abstraction from ColabSession."

## Alternatives Considered

**Multi-provider from the start.** Rejected because:
- Speculative abstraction adds complexity without proven need.
- YAGNI: we don't know what a second provider's API would look like.
- The Rule of Three principle prohibits abstractions with fewer than three implementations.

## References

- CONSTITUTION.md, Rule 1 (Single Identity)
- CONSTITUTION.md, Rule 2 (Google Colab Only)
- CONSTITUTION.md, Rule 7 (Minimal Abstraction)
