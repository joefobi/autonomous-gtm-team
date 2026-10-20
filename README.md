# Hospital GTM Team

This project is a bounded go-to-market research team for exploring whether
hospital patient-flow operations may be a useful market for an ER bed
availability product. It is deliberately a discovery workflow: public
evidence does not establish a hospital's buyer, data availability, product
need, or willingness to run a pilot.

## Project description

### Problem

Hospital operations teams may have challenges coordinating emergency arrivals,
staffed capacity, inpatient bed readiness, and discharge timing. The team turns
public evidence and explicitly labeled discovery feedback into a shortlist,
strategy, founder decision request, and reviewable outreach draft. It does not
invent operational metrics, claim clinical benefit, or send external messages.

### Agent team and handoffs

Band Desktop is the coordination harness. Each role is a Codex agent configured
with the corresponding prompt in `prompts/`, while this repository provides the
Python memory and workflow tools:

| Role | Responsibility | Handoff |
| --- | --- | --- |
| Strategist | Owns the Band plan and board, recalls memory, proposes strategy, and asks for founder approval. | Assigns research and receives the researcher handoff. |
| Researcher | Uses Band/Codex native web search, preserves provenance for selected pages, and writes ready memory records. | Mentions the strategist with the hospital ID, task ID, queries, discovered URLs, record IDs, limitations, and open questions. |
| Outreach writer | Retrieves the approved strategy and drafts source-grounded discovery outreach. | Receives only a current, founder-approved strategy version; never sends externally. |

Band remains the source of truth for rooms, plans, tasks, messages, and human
questions. The application does not create a second local orchestrator.

### Cognee memory

The shared memory service has two layers:

1. SQLite is the canonical record store. It retains the hospital namespace,
   provenance, evidence status, idempotency key, strategy version, and indexing
   state.
2. Cognee is the optional semantic index used for recall. Writes are serialized
   through the memory service, and recall is filtered back to the canonical
   SQLite records for the requested hospital.

Every research finding stores its source URL or file, title, access date, and
excerpt. A fresh agent session can retrieve the canonical record IDs and use
them to change a strategy. The deterministic keyword index remains available
for local tests and environments without Cognee.

## Development

Create a project-local virtual environment and install the development tools:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev,demo]"
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

The researcher discovers sources with the native Band/Codex web-search tools;
this repository fetches and records only the URLs the agent selected. It does
not assert a customer need or buying intent. The `customer` track evaluates a
possible buyer for the built model; the `data_collaboration` track evaluates a
research or data partnership. Search topics and outreach language change with
the selected track.

## Band coordination

PR2 uses the installed Band CLI for shared rooms, plans, tasks, handoffs, and
founder questions. Configure the three role prompts in `prompts/`, publish
`plans/hospital-evaluation.md`, and follow `docs/band-setup.md` for the
two-agent smoke test. The adapter reports command failures instead of claiming
that an unavailable Band integration completed.

## GTM workflow

PR3 adds agent-led live research, strategy versions, founder approval,
draft-only outreach, founder-confirmed discovery feedback, and fresh-session
strategy revision.
See `docs/gtm-workflow.md` for the live-source workflow and `outputs/` for
generated artifacts.

## Flexprice and Snyk

Neither Flexprice nor Snyk is used in this implementation. Flexprice billing
and usage accounting were kept out of the three core workflows. Snyk scanning
was also not added; CI currently runs only `black`, `isort`, `mypy`, and the
Python test suite. These integrations can be added after the Band, memory, and
GTM workflows are verified.

## Demo video

The required two-to-three-minute recording runbook is in
[`docs/demo-video.md`](docs/demo-video.md). It captures Band Desktop's room,
moving work board, founder decision, and usage/cost view, then shows a fresh
memory recall changing the recommendation. Use a fresh room and database for
each recording so the state is easy to follow.
