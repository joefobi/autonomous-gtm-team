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
.venv/bin/black --check src tests
.venv/bin/isort --check-only src tests
.venv/bin/mypy src
.venv/bin/python -m unittest discover -s tests
```

## Shared memory service

Start the loopback service with a persistent SQLite database:

```bash
.venv/bin/memory-client serve --db data/memory.sqlite3
```

The service exposes `POST /memories`, `GET /memories/{id}`, `POST /recall`,
`POST /decisions`, and `GET /health`. SQLite stores canonical records,
provenance, idempotency keys, indexing state, and decisions. The default
keyword index is deterministic and local; Cognee can be selected with
`--index cognee --dataset hospital_gtm` after installing and configuring it.

The first public-evidence fixture uses The Johns Hopkins Hospital and records
only a sourced public page reference. It does not assert a customer need or
buying intent.

## Band coordination

PR2 uses the installed Band CLI for shared rooms, plans, tasks, handoffs, and
founder questions. Configure the three role prompts in `prompts/`, publish
`plans/hospital-evaluation.md`, and follow `docs/band-setup.md` for the
two-agent smoke test. The adapter reports command failures instead of claiming
that an unavailable Band integration completed.

## GTM workflow

PR3 adds sourced research, strategy versions, founder approval, draft-only
outreach, simulated discovery feedback, and fresh-session strategy revision.
See `docs/gtm-workflow.md` for the runnable demo and `outputs/` for committed
example artifacts.

## Agent evals

PR4 adds scenario-based evaluations for live Band runs. Use the exact user
prompts in `evals/scenarios/`, capture the room and memory artifacts, and run
`agent-eval`; see `evals/README.md` and `evals/rubric.md` for deterministic
checks and human review.
