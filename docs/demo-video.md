# Demo video runbook

Record one continuous two-to-three-minute walkthrough. The goal is to show
coordination in Band Desktop and a memory-backed change in agent behavior, not
to explain every implementation detail.

## Before recording

Use a clean checkout, a project-local environment, and a fresh database:

```bash
source .venv/bin/activate
.venv/bin/python -m pip install -e ".[dev]"
mkdir -p data
rm -f data/demo-memory.sqlite3
band --version
band preflight
```

Install and configure Cognee according to its local setup requirements before
starting the service. Then run the shared memory service in a separate terminal:

```bash
.venv/bin/memory-client serve \
  --db data/demo-memory.sqlite3 \
  --index cognee \
  --dataset hospital_gtm
```

If Cognee is unavailable, do not present the keyword fallback as a Cognee demo.
Use the fallback for development only and disclose it in the recording notes.

In Band Desktop:

1. Confirm the strategist, researcher, and outreach writer agents are
   connected and use this repository as their working directory.
2. Create a fresh room with the strategist and researcher.
3. Keep the Work and Usage views available for the recording.

The actual handles are installation-specific. Set shell variables after Band
returns them:

```bash
export ROOM_ID="ROOM_ID_FROM_BAND"
export STRATEGIST="OWNER/hospital-gtm-strategist"
export RESEARCHER="OWNER/hospital-gtm-researcher"
export HOSPITAL_ID="johns_hopkins_hospital"
export SOURCE_ONE="https://www.hopkinsmedicine.org/patient-care/locations/the-johns-hopkins-hospital"
export SOURCE_TWO="https://www.hopkinsmedicine.org/emergency-medicine/patient-information"
```

## Recording sequence

### 0:00–0:25 — Introduce the team

Show the Band Desktop room and participants. Say:

> The strategist owns the plan, the researcher gathers source-backed evidence,
> and the outreach writer drafts only after founder approval. Band coordinates
> the work; the shared memory service persists evidence.

Publish the plan and assign the task from the strategist identity:

```bash
band plan set "$ROOM_ID" plans/hospital-evaluation.md \
  --snapshot --as "$STRATEGIST"
band work assign "$ROOM_ID" "Research hospital patient-flow priorities" \
  --detail "Read supplied public sources, write sourced memory, and hand off record IDs and unknowns." \
  --component research --component memory_service --as "$STRATEGIST"
```

Switch to the Band Work view and show the task as `To do`.

### 0:25–0:55 — Show the board moving and the handoff

Send the strategist this room prompt, or use the configured strategist agent:

```text
For the hospital under evaluation, read the supplied live public sources and
recall existing memory. Assign the researcher and require a sourced memory
write before completion. The researcher handoff must include the task ID,
canonical record IDs, provenance, limitations, and open questions. Do not
contact anyone externally.
```

Show the board move from `To do` to `In progress`, the researcher message, and
the explicit strategist handoff. The handoff should include the canonical
memory record ID and an `indexing_state` of `ready`.

### 0:55–1:20 — Show the human decision

Run the workflow against the Cognee-backed service using live public sources.
Replace the URLs with the hospital and source set you are actually evaluating:

```bash
.venv/bin/gtm-demo \
  --hospital-id "$HOSPITAL_ID" \
  --source "$SOURCE_ONE" \
  --source "$SOURCE_TWO" \
  --feedback /tmp/actual-discovery-feedback.json \
  --feedback-status founder_confirmed \
  --memory-url http://127.0.0.1:8765 \
  --outputs outputs \
  --room-id "$ROOM_ID" \
  --strategist "$STRATEGIST" \
  --researcher "$RESEARCHER"
```

When Band asks for approval, show the question in Band Desktop and select
`approved`. Point out that the outreach output is a draft and that no external
message is sent.

### 1:20–1:55 — Show memory changing the recommendation

Open the memory-backed output and show the initial and revised strategy. Then
run a fresh recall from another terminal:

```bash
.venv/bin/memory-client recall \
  "$HOSPITAL_ID" \
  "inpatient bed readiness and discharge coordination" \
  --url http://127.0.0.1:8765
```

Use the returned record ID with `get`:

```bash
.venv/bin/memory-client get RECORD_ID --url http://127.0.0.1:8765
```

Explain that the public pages are sourced and the feedback file contains the
actual note from the discovery conversation. The fresh strategy changes only
if that persisted note supports a changed recommendation; the fresh prompt
must not repeat the hidden feedback.

### 1:55–2:20 — Show usage/cost and close

Open Band Desktop's Usage view and show the room or agent usage/cost details.
Do not invent a dollar amount if the installed Band release does not expose
one; show the available usage view and say what is available. End on the Band
room with the completed task, founder decision, and memory-backed output.

## Evidence to keep with the video

Save these artifacts next to the recording or in the evaluation run artifact:

- Band room ID and screenshot of the plan, board transition, handoff, and
  founder decision.
- The memory recall response and the canonical record retrieved with `get`.
- `outputs/$HOSPITAL_ID/learning_summary.json`.
- The final `gtm-demo` JSON output listing generated files.
- A note stating whether the Usage view showed a monetary cost or only usage
  counters.

Do not fabricate a discovery note for the recording. Create
`/tmp/actual-discovery-feedback.json` from a real conversation or founder
decision, preserve its source and date, and remove it after the recording if it
contains sensitive information.
