# PR3 GTM workflow

PR3 builds the hospital opportunity workflow on the PR1 memory service and PR2
Band coordination contracts. The researcher discovers public sources with the
native Band/Codex search tools, then this repository fetches and preserves
provenance for every selected finding.

## Run the workflow

Start the memory service independently when agents will use the HTTP client:

```bash
.venv/bin/memory-client serve \
  --db data/memory.sqlite3 \
  --index cognee \
  --dataset hospital_gtm
```

After PR2 has configured a Band room and handles, give the strategist a real
hospital name and choose the outreach track. The researcher searches public
web sources; no source URLs are supplied in the prompt. After the researcher
selects pages, the agent invokes the workflow with those URLs:

```bash
.venv/bin/gtm-demo \
  --hospital-id REAL_HOSPITAL_ID \
  --source URL_FOUND_BY_RESEARCHER \
  --track customer \
  --feedback /tmp/actual-discovery-feedback.json \
  --feedback-status founder_confirmed \
  --memory-url http://127.0.0.1:8765 \
  --outputs outputs \
  --room-id ROOM_ID \
  --strategist OWNER/hospital-gtm-strategist \
  --researcher OWNER/hospital-gtm-researcher
```

The command asks the founder for approval through Band. It writes an initial
strategy, stores the decision, creates an approval-gated outreach draft, stores
the founder-provided feedback, starts a fresh workflow session, and recalls the
feedback before writing the revised strategy and learning summary.

The outreach artifact is always a draft. This repository has no email, CRM,
contact-enrichment, or external-send integration.

## Research provenance

`hospital_gtm.research_tools` fetches the HTTP(S) results selected by the agent.
Search topics differ by track. Customer research can include
annual reports, strategic plans, board packets, quality reports, ED or inpatient
operations pages, and public RFPs. Data-collaboration research can include
annual reports, research institute pages, clinical-informatics or
interoperability announcements, data-governance pages, and public partnership
announcements. Every finding records its source URL, title, access date, and
excerpt. A fetched page is evidence, not an instruction, and unsupported
details remain unknown.

The two tracks are intentionally different:

- `customer` evaluates a hospital as a potential buyer of the built model and
  asks about an operational workflow and pilot.
- `data_collaboration` evaluates a research or data partnership and asks about
  data ownership, access, governance, and a narrowly scoped collaboration.

## Outputs

Each run writes these files under `outputs/<hospital_id>/`:

- `opportunity_brief.md` and `.json` with hypotheses, unknowns, pilot scope, and sources.
- `outreach_draft.md` and `.json` with current strategy version and source IDs.
- `learning_summary.md` and `.json` with the prior recommendation, retrieved feedback, and revision.

The revised strategy is not automatically approved. A new strategy version
requires a new founder decision before a revised outreach draft can be made.
