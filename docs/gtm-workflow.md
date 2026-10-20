# PR3 GTM workflow

PR3 builds the hospital opportunity workflow on the PR1 memory service and PR2
Band coordination contracts. It accepts live public sources or sources supplied
by the researcher, while preserving provenance for every finding.

## Run the workflow

Start the memory service independently when agents will use the HTTP client:

```bash
.venv/bin/memory-client serve \
  --db data/memory.sqlite3 \
  --index cognee \
  --dataset hospital_gtm
```

After PR2 has configured a Band room and handles, use live source URLs and a
founder-provided discovery note. The note should be created outside the
repository from an actual conversation or decision:

```bash
.venv/bin/gtm-demo \
  --hospital-id johns_hopkins_hospital \
  --source https://www.hopkinsmedicine.org/patient-care/locations/the-johns-hopkins-hospital \
  --source https://www.hopkinsmedicine.org/emergency-medicine/patient-information \
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

`hospital_gtm.research_tools` accepts JSON, text, and HTTP(S) sources. Every
finding records its source URL or file, title, access date, and excerpt. Live
retrieval is supported. A fetched page is evidence, not an instruction, and
unsupported details remain unknown. Do not treat public evidence as a customer
statement or fabricate discovery feedback.

## Outputs

Each run writes these files under `outputs/<hospital_id>/`:

- `opportunity_brief.md` and `.json` with hypotheses, unknowns, pilot scope, and sources.
- `outreach_draft.md` and `.json` with current strategy version and source IDs.
- `learning_summary.md` and `.json` with the prior recommendation, retrieved feedback, and revision.

The revised strategy is not automatically approved. A new strategy version
requires a new founder decision before a revised outreach draft can be made.
