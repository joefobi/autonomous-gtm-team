"""GTM tracks that shape live research and outreach."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OutreachTrack(str, Enum):
    """Commercial or collaboration objective for a hospital evaluation."""

    CUSTOMER = "customer"
    DATA_COLLABORATION = "data_collaboration"


@dataclass(frozen=True, slots=True)
class TrackConfig:
    """Research and outreach instructions for one GTM track."""

    name: str
    objective: str
    search_topics: tuple[str, ...]
    buyer_hypotheses: tuple[str, ...]
    outreach_action: str


TRACK_CONFIGS: dict[OutreachTrack, TrackConfig] = {
    OutreachTrack.CUSTOMER: TrackConfig(
        name="built-model customer",
        objective=(
            "Evaluate whether hospital operations teams have a patient-flow "
            "problem worth exploring as a product pilot."
        ),
        search_topics=(
            "annual report strategic priorities patient flow",
            "emergency department operations capacity wait times",
            "inpatient bed capacity discharge coordination",
            "quality report board meeting patient flow",
        ),
        buyer_hypotheses=(
            "ED operations leadership may own arrival and treatment-space planning.",
            "Inpatient flow or bed-management leadership may own readiness and boarding.",
        ),
        outreach_action="Request a discovery conversation about an operational workflow and pilot.",
    ),
    OutreachTrack.DATA_COLLABORATION: TrackConfig(
        name="data collaboration",
        objective=(
            "Evaluate whether the hospital has a research, analytics, or "
            "informatics collaboration relevant to the product hypothesis."
        ),
        search_topics=(
            "annual report research analytics strategic priorities",
            "clinical informatics interoperability data platform",
            "research partnership data sharing innovation center",
            "public data governance research collaboration announcement",
        ),
        buyer_hypotheses=(
            "Clinical informatics or analytics leadership may sponsor a data evaluation.",
            "A research or innovation office may own external data collaborations.",
        ),
        outreach_action=(
            "Request a conversation about data ownership, access, governance, and "
            "a narrowly scoped collaboration."
        ),
    ),
}


def track_config(track: OutreachTrack) -> TrackConfig:
    """Return configuration for a GTM track.

    Args:
        track: Selected GTM track.

    Returns:
        Track-specific research and outreach configuration.
    """
    return TRACK_CONFIGS[track]
