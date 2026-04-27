# Contributing Guide

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Coding rules

- Keep changes non-destructive by default.
- Preserve module boundaries (`core/`, `modules/`, `gui/`).
- Add tests for new logic-heavy behavior.
- Avoid introducing offensive or bypass-like capabilities.

## Pull request checklist

1. Add/update tests for changed behavior.
2. Update docs (`README.md`, `CHANGELOG.md`) when feature-facing changes are made.
3. Keep commits focused and descriptive.
4. Confirm app still launches (`python main.py`).
