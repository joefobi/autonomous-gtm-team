# Demo video runbook

Record one continuous two-to-three-minute walkthrough. The demo uses a real
hospital and native Band/Codex web search. Do not paste source URLs into the
agent prompt, check in a source pack, or present prepared research as autonomous
work.

## Local preparation

The coding agent can perform the local preparation from this repository. It
does not require you to activate a virtual environment or type Python commands:

```text
Prepare a fresh demo for [REAL HOSPITAL NAME] using the [customer or
data_collaboration] track. Start the Cognee-backed memory service, verify Band,
and report the exact room and agent handles I need for the recording. Do not
provide source URLs; the researcher must use native Band/Codex search.
```

The local service must use persistent storage and Cognee, not the keyword
fallback. If Cognee cannot initialize, stop and disclose the blocker rather
than recording a misleading memory demo.

## Band preparation

In Band Desktop, confirm the three configured agents use this repository and
the prompts in `prompts/`. Create a fresh room with the strategist and
researcher, and keep Work and Usage visible. The founder chooses one track:

- `customer`: possible buyer for the built patient-flow model.
- `data_collaboration`: research or data partnership around access, governance,
  and operational data.

The task should name only the real hospital and selected track. It should not
contain a list of URLs. The researcher should use native search to find examples such
as annual reports, strategic plans, board packets, quality reports, ED or
inpatient operations pages, public RFPs, research institute pages, clinical
informatics announcements, and data-governance or partnership pages.

## Recording sequence

### 0:00–0:25 — Introduce the team

Show the Band room and participants. Say:

> The strategist owns the plan, the researcher searches public sources natively,
> and the outreach writer drafts only after founder approval. Band coordinates
> the work; Cognee-backed memory persists the evidence and decisions.

Show the strategist assigning the researcher a task containing the hospital ID
and track, but no source URLs. The task requires source provenance, unknowns,
and a ready memory write before completion.

### 0:25–0:55 — Show live research and handoff

Show the board move from `To do` to `In progress`. Show the researcher’s native
search queries and selected public pages, then the memory write response with a
canonical record ID and `indexing_state: ready`. Show the handoff to the
strategist with the query, source URL, title, access date, excerpt, record IDs,
limitations, and open questions.

### 0:55–1:20 — Show the human decision

Show the strategist’s initial recommendation, with buyer hypotheses and
unknowns separated from sourced claims. When Band asks for approval, select
`approved` or `revise` explicitly. Show that outreach remains blocked until the
decision matches the current strategy version.

### 1:20–1:55 — Show memory changing the recommendation

Have the founder add an actual discovery note through the Band workflow. It may
change the priority from arrival forecasting to inpatient bed readiness, but do
not invent a quote or label founder feedback as public evidence. Store the note
with its correct evidence status.

Start a fresh strategist session with only the hospital ID, track, and request
for the next meeting. Do not paste the discovery note into the new prompt. Show
the recall record IDs and the revised recommendation. Then show the outreach
writer receiving the approved current strategy and creating a draft only.

### 1:55–2:20 — Show usage and close

Open Band Desktop’s Usage view and show the available agent usage or cost
details. Do not invent a dollar amount if the installed release exposes only
usage counters. End on the Band room with the completed task, founder decision,
memory-backed revision, and unsent draft.

## Evidence to keep with the video

- Band room ID and screenshots of the plan, board transition, handoff, and decision.
- The native search queries and fetched source provenance.
- The Cognee recall response and canonical record retrieved with `get`.
- `outputs/<real_hospital_id>/learning_summary.json`.
- A note stating whether Usage showed monetary cost or only usage counters.

Do not fabricate a discovery note or public source. If a live search or Band
integration is unavailable, record that as a limitation and do not claim the
demo completed.
