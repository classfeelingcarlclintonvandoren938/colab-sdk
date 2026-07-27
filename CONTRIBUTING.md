# Contributing — Colab SDK

> How to contribute to the project.

---

## Getting Started

```bash
git clone https://github.com/heyncth/colab-sdk
cd colab-sdk
pip install -e ".[dev]"
```

## Prerequisites

- Python 3.10+
- `google-colab-cli` installed (`pip install google-colab-cli`)
- Google account with Colab access
- Authentication is auto-triggered on first `colab new` — no separate login step required

## Development Workflow

1. Read `CONSTITUTION.md` — understand project rules
2. Read `AGENTS.md` — understand AI behavior expectations
3. Read the relevant component `SPEC.md` before implementing
4. Follow the coding standards in `CODING_STANDARDS.md`
5. Write unit tests for all new code
6. Run pre-commit checks before pushing

## Before Making Changes

- Check `docs/PROGRESS.md` to understand what's been done
- Check existing ADRs before changing architecture
- If changing a component's interface, update its `SPEC.md`

## Commit Guidelines

```
<type>: <brief description>

<optional body>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:
```
feat: add static dependency analysis for wildcard imports
docs: update analyzer SPEC with edge case handling
fix: handle session timeout during artifact upload
```

## PR Guidelines

- One logical change per PR
- Include tests for new functionality
- Update SPEC.md if component behavior changes
- Add ADR if the PR introduces a new architectural decision
- Reference related ADRs and issues

## Code Review

All PRs must be reviewed by at least one maintainer. AI-generated code is welcome but must be reviewed by a human maintainer before merging.

## Running Tests

```bash
pytest                          # All tests
pytest tests/test_analyzer.py   # Analyzer tests only
pytest -x                       # Stop on first failure
```

## Building

```bash
pip install build
python -m build
```

## License

MIT
