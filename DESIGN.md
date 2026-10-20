# Hospital GTM Team Design

## Purpose

Build a small Band-coordinated agent team that helps a founder evaluate a real
hospital using public evidence and customer discovery. The product hypothesis
concerns ED demand, staffed bed availability, discharge timing, and patient
flow. Public evidence does not establish a buyer, data availability, product
need, or willingness to run a pilot.

The prototype uses Band Desktop for coordination and Cognee Open Source for
persistent shared memory. The founder chooses one of two research tracks:

- `customer`: evaluate the hospital as a possible buyer of the built model.
- `data_collaboration`: evaluate a research or data partnership around data
  access, governance, and a narrowly scoped collaboration.

## Scope

Include one real hospital evaluation, three agents, live public research,
source provenance, persistent memory, a founder decision, a structured
opportunity brief, and a draft-only outreach artifact.

Exclude clinical prediction, EHR connections, patient data, bed assignment,
email sending, contact enrichment, bulk prospecting, and a full CRM.

The researcher must autonomously search public sources with the native search
tools available in Band/Codex. Do not provide a source URL list in the prompt.
After searching, the agent passes selected URLs to this repository for fetching
and provenance storage. Search examples include annual reports,
strategic plans, board packets or minutes, quality reports, ED and inpatient
operations pages, public RFPs, research institute pages, clinical informatics or
interoperability announcements, data-governance pages, and partnership
announcements. Search topics depend on the selected track.

## Architecture

Band Desktop creates and runs the configured agents. Each agent uses the same
working directory and a small Python client for shared memory. Band remains the
source of truth for rooms, plans, tasks, messages, human questions, and usage.

A single loopback memory service owns the Cognee connection and serialized
writes. SQLite stores canonical records and exact provenance; Cognee provides
semantic recall. The service filters recall by hospital before returning
canonical records. Storage must survive agent restarts.

| Component | Responsibility |
| --- | --- |
| Band Desktop | Agent configuration, room, board, handoffs, founder decision, usage |
| Agent harnesses | Model reasoning and permitted search/tool execution |
| Memory client | Validated requests to the local service |
| Memory service | Cognee writes and reads, serialized writes, persistence |
| SQLite store | Canonical records, provenance, hospital isolation, idempotency |
| Research tools | Webpage retrieval and provenance-preserving extraction |
| Output writer | Markdown and JSON briefs, drafts, and learning summaries |

## Workflow

1. The founder gives the strategist a real hospital name and selects a track.
2. The strategist recalls prior hospital context and creates the Band plan.
3. The researcher claims the task and searches public sources with native
   Band/Codex tools.
4. The researcher passes selected URLs to the repository, which stores findings
   with URL, title, access date, and excerpt,
   then waits for indexing to be ready.
5. The researcher hands the strategist record IDs, findings, limitations, and
   open questions through Band.
6. The strategist recalls the findings and proposes a track-specific direction.
7. The strategist asks the founder for an explicit decision through Band.
8. The decision is stored against the exact strategy version.
9. The strategist hands the approved approach to the outreach writer.
10. The outreach writer recalls evidence and approval, then creates a draft.
11. New discovery feedback is stored. A fresh strategist session recalls it and
    revises the next recommendation.

No approval is implied by elapsed time. A revised strategy invalidates prior
approval for dependent outreach until the founder approves the new version.
No external message is sent.

## Agent responsibilities

### Strategist

The strategist owns the shared plan and board, selects or confirms the track,
assigns research, recalls memory, separates facts from hypotheses and
feedback, proposes buyer roles and discovery questions, requests founder
approval, and explains what recalled information changed the recommendation.

### Researcher

The researcher searches the public web without a supplied source list, uses the
track's source categories and native Band/Codex tools, then passes selected
URLs to the repository for fetching. It extracts supported claims, retains provenance,
reports unknowns and contradictions, writes ready memory records, and hands
the strategist canonical record IDs.

### Outreach writer

The outreach writer verifies that approval matches the current strategy and
track, drafts a concise discovery message grounded in sourced records, asks for
review, and never sends externally.

## Memory contract

Each record has a stable ID, hospital ID, kind, content, evidence status,
timestamp, author, source metadata, and links to supporting records. Kinds are
public evidence, hypothesis, discovery feedback, founder decision, strategy,
and outreach draft. Evidence status distinguishes sourced, unverified,
simulated, and founder-confirmed information.

The memory API provides `POST /memories`, `GET /memories/{id}`, `POST /recall`,
`POST /decisions`, and `GET /health`. Writes are serialized and idempotent.
Cross-hospital recall is rejected or filtered. Conflicting records remain in
history and must be surfaced rather than silently overwritten.

## Outputs and verification

The opportunity brief contains supported observations, track-specific buyer
hypotheses, unknowns, discovery questions, pilot or collaboration scope, data
needs, source references, and founder decision context. Outreach remains a
draft. A learning summary shows the prior recommendation, recalled feedback,
and revised recommendation.

Verify that:

- a different session retrieves a record written by another agent;
- live source claims retain URL, title, access date, and excerpt;
- hospital filtering prevents cross-hospital leakage;
- duplicate retries do not create duplicate records;
- founder approval gates dependent outreach;
- new feedback changes a fresh-session recommendation;
- Band shows the room, board movement, handoff, decision, and usage view;
- no external message is sent.

## Optional integrations

Flexprice metering, Snyk scanning, live UI work, and other integrations remain
out of the core workflow until Band coordination, live research, Cognee memory,
and approval-gated outputs are verified.
