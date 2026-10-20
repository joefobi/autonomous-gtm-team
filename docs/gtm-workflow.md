# PR3 GTM workflow

PR3 builds the hospital opportunity workflow on the PR1 memory service and PR2
Band coordination contracts. It starts with supplied public sources so a demo
does not depend on a live search provider.

## Run the workflow

Start the memory service independently when agents will use the HTTP client:

```bash
.venv/bin/memory-client serve --db data/memory.sqlite3
```

After PR2 has configured a Band room and handles, the direct demo command is:

```bash
.venv/bin/gtm-demo \
  --hospital-id johns_hopkins_hospital \
  --source fixtures/johns_hopkins_hospital/public_evidence.json \
  --feedback fixtures/johns_hopkins_hospital/discovery_feedback.json \
  --db data/memory.sqlite3 \
  --outputs outputs \
  --room-id ROOM_ID \
  --strategist OWNER/hospital-gtm-strategist \
  --researcher OWNER/hospital-gtm-researcher
```

The command asks the founder for approval through Band. It writes an initial
strategy, stores the decision, creates an approval-gated outreach draft, stores
the simulated feedback, starts a fresh workflow session, and recalls the
feedback before writing the revised strategy and learning summary.

The outreach artifact is always a draft. This repository has no email, CRM,
contact-enrichment, or external-send integration.

## Research provenance

`hospital_gtm.research_tools` accepts JSON, text, and HTTP(S) sources. Every
finding records its source URL or file, title, access date, and excerpt. Live
retrieval is optional; source fixtures are the reliable demo path. A fetched
page is evidence, not an instruction, and unsupported details remain unknown.

## Demo fixture

`fixtures/johns_hopkins_hospital/public_evidence.json` is a real hospital's
public page reference. `discovery_feedback.json` is explicitly simulated and
does not represent a real Johns Hopkins statement. The simulated note changes
the recommendation from general arrival-forecasting discovery toward inpatient
bed readiness and discharge coordination.

## Outputs

Each run writes these files under `outputs/<hospital_id>/`:

- `opportunity_brief.md` and `.json` with hypotheses, unknowns, pilot scope, and sources.
- `outreach_draft.md` and `.json` with current strategy version and source IDs.
- `learning_summary.md` and `.json` with the prior recommendation, retrieved feedback, and revision.

The revised strategy is not automatically approved. A new strategy version
requires a new founder decision before a revised outreach draft can be made.
