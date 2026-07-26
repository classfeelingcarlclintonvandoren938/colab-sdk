# ADR-005: Minimal Abstraction

**Status:** Accepted

---

## Context

Software projects naturally accumulate layers of abstraction over time: base classes, interfaces, factories, registries, managers, providers.

For each potential abstraction, the project must decide: does this abstraction earn its existence, or is it speculative?

## Decision

**Introduce no abstraction without justification from multiple concrete implementations.**

This means:
- No `BaseProvider` (only Colab, no second provider)
- No `Runtime` interface (only one runtime)
- No `ProviderFactory` (nothing to create)
- No `SessionManager` (one session per App, no management needed)
- No `AbstractAnalyzer` (one analysis algorithm)
- No `PackagerInterface` (one packaging strategy)

```python
# Each component is a concrete class:
class Analyzer: ...
class Packager: ...
class ColabSession: ...
class ExecutionEngine: ...
class App: ...
class RemoteFunction: ...
```

The Rule of Three is the gate: no abstraction is extracted until there are at least three concrete implementations that share common behavior.

## Rationale

- **Speculative abstraction is the #1 cause of over-engineering** in OSS projects. It produces interfaces designed for use cases that never materialize.
- **Abstraction has a cost**: more files, more indirection, harder debugging, longer onboarding, more test scaffolding.
- **Refactoring is cheap**: Extracting an interface from three concrete implementations is straightforward and safe with modern tooling. Doing it preemptively is not.
- **YAGNI**: You aren't going to need it. The second runtime may have fundamentally different requirements that don't fit the abstraction we design today.

## Trade-offs

- Adding a second runtime later requires refactoring: extracting interfaces, updating all consumers, writing compatibility layers.
- This refactoring cost is accepted as a deliberate trade-off. It is smaller than the cumulative cost of maintaining unused abstractions from day one.

## Consequences

- Every component in the codebase is a concrete class with a single implementation.
- No `interface`, `Protocol`, `ABC`, or `base` module exists.
- New components follow the same pattern: concrete class first, abstraction later if needed.
- AI agents are explicitly instructed (in AGENTS.md and CONSTITUTION.md) not to introduce speculative abstractions.

## Alternatives Considered

**Provider abstraction from the start.** Rejected because it violates the Rule of Three and would add complexity without any proven need. The abstraction would be designed for an imaginary second runtime.

**Repository/Service pattern.** Rejected as unnecessary for a client-side SDK with no database, no API server, and no persistent storage.

## References

- CONSTITUTION.md, Rule 7 (Minimal Abstraction)
- CONSTITUTION.md, Rule 1 (Single Identity)
- AGENTS.md, Rule 5 (Never speculative abstractions)
