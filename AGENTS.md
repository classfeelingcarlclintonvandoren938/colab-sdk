# AGENTS — AI Execution Rules

> Instructions for AI agents working on the Colab Client codebase.

---

## Before Making Changes

1. **Read CONSTITUTION.md first.** Never violate a constitutional rule.
2. **Read CODING_STYLE.md** before writing any code. Follow the Python style rules.
3. **Read the relevant SPEC.md** before implementing a component. SPEC is the contract.
4. **Read the relevant ADRs** before modifying architecture. Understand why decisions were made.
5. **Check PROGRESS.md** to understand the current session state and what's already been done.

## During Implementation

5. **Never add speculative abstractions.** If you are tempted to add a `BaseProvider`, `AbstractSession`, or `RuntimeFactory`, stop and read `CONSTITUTION.md` rules 1, 7.
6. **Prefer simplicity.** When two implementations achieve the same goal, choose the simpler one. Fewer files, fewer classes, fewer layers of indirection.
7. **Fail fast.** Validate configuration at decoration time, not runtime. Let the user know about errors immediately.
8. **Use `google-colab-cli`** for all Colab interactions. Do not implement custom HTTP requests to Colab APIs, do not use Selenium, do not scrape cookies.
9. **Keep components isolated.** An implementation change in the Session component should not require changes in the Analyzer component. Follow the protocol contracts.

## After Implementation

10. **Update PROGRESS.md** with what was implemented, what decisions were made, and what blockers remain.
11. **Check for stale decisions.** If implementation reveals that an ADR was wrong, open a discussion — do not silently violate it.
12. **Add tests.** Unit tests are mandatory for the Analyzer, Packager, and Session components. Integration tests with real Colab are manual for MVP.

## Design Constraints

- **Python 3.10+** required. Use standard library when possible.
- **No asyncio** for MVP. Synchronous execution is sufficient.
- **No WebSocket** for MVP. `colab exec` streams stdout natively.
- **No database.** The SDK has zero server-side state.
- **Minimal dependencies.** `google-colab-cli` is the only required external dependency.

## Reading Order for Common Tasks

**Implementing a new component:** CONSTITUTION → AGENTS → CODING_STYLE → CODING_STANDARDS → foundation/ARCHITECTURE → relevant protocols → component/SPEC → component/ADR

**Debugging a component:** PROGRESS → component/ADR → component/SPEC → component source code

**Understanding the product:** CONSTITUTION → foundation/PRD → foundation/ARCHITECTURE → examples/
