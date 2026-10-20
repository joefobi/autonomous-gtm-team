# Hospital GTM Team

Agent Coord is the Python foundation for the hospital GTM agent team described
in the project design. The package uses a `src` layout so the service, client,
and workflow modules can be added without making the repository root importable.

## Development

Create a project-local virtual environment and install the development tools:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Run the same checks used in CI:

```bash
.venv/bin/black --check src
.venv/bin/isort --check-only src
.venv/bin/mypy src
```
