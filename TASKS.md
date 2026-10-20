# Implementation Tasks

The existing CI and package setup is the foundation. Implement the design in
three sequential pull requests.

## PR 1 — Shared Memory Foundation

Implement the persistent memory layer independently of Band.

### Tasks

- [ ] Add validated records, decisions, indexing states, and recall results in `src/models.py`.
- [ ] Add a SQLite canonical record store with provenance and hospital isolation.
- [ ] Add a Cognee adapter with persistent storage and serialized writes.
- [ ] Add `POST /memories`.
- [ ] Add `GET /memories/{id}`.
- [ ] Add `POST /recall`.
- [ ] Add `POST /decisions`.
- [ ] Add `GET /health`.
- [ ] Add idempotency handling and duplicate-write protection.
- [ ] Add CLI commands such as `remember`, `recall`, and `get`.
- [ ] Verify one real hospital using public evidence found by the agent's native search.
- [ ] Test persistence, provenance, hospital filtering, idempotency, and cross-process recall.

### Acceptance

One process writes a record and a fresh process retrieves it with its canonical
record ID and evidence status.

## PR 2 — Band Agent Coordination

Implement the multi-agent workflow through Band. Do not create a second
orchestrator.

### Tasks

- [ ] Add role prompts for strategist, researcher, and outreach writer.
- [ ] Document the Band shared room and working directory setup.
- [ ] Add strategist-owned plan and board tasks.
- [ ] Add researcher task assignment and completion evidence.
- [ ] Define explicit researcher-to-strategist handoff payloads.
- [ ] Prove a two-agent vertical slice before enabling all three roles.
- [ ] Add founder decision requests with options, recommendation, rationale, and pending action.
- [ ] Add strategy versioning and approval validation.
- [ ] Document actual Band commands, capabilities, and unavailable integrations.

### Acceptance

Two agents visibly collaborate in one Band room, complete a task, perform a
handoff, and wait for an explicit founder decision.

## PR 3 — Hospital GTM Workflow and Outputs

Build the domain workflow on top of the memory and Band foundations.

### Tasks

- [ ] Use Band/Codex native search, then use `src/research_tools.py` to fetch selected URLs and preserve provenance.
- [ ] Extract source URL or file, title, access date, and excerpts.
- [ ] Generate strategy with buyer hypotheses, unknowns, discovery questions, and pilot scope.
- [ ] Store founder decisions linked to the approved strategy version.
- [ ] Generate outreach drafts that verify current approval.
- [ ] Generate a structured opportunity brief and learning summary.
- [ ] Store generated files under `outputs/`.
- [ ] Record an explicitly labeled discovery note showing the shift from arrival forecasting to inpatient bed readiness.
- [ ] Demonstrate fresh-session recall changing the recommendation.
- [ ] Verify sourced claims and simulated labels.
- [ ] Verify conflicting evidence remains visible.
- [ ] Verify strategy-version invalidation.
- [ ] Verify approval-gated outreach.
- [ ] Verify no external message is sent.

### Acceptance

The full demo workflow runs from research through founder approval, outreach
draft, new feedback, persistent recall, and revised recommendation.

## Dependency Order

```text
PR 1: memory contracts → PR 2: Band coordination → PR 3: GTM workflow
```

Keep optional billing, security scanning, and UI work out of
these PRs until the three core workflows are verified.
