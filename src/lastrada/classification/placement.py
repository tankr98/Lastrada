from lastrada.schemas.models import Classification, Placement


def classify(percent, intervals, sections=(), expert=False):
    if percent is None:
        return Classification()
    # "entire" is only literal full coverage; 95% is an experimental archetype threshold.
    category = (
        "entire"
        if percent >= 99.999
        else "more_than_25_percent"
        if percent > 25
        else "25_percent_or_less"
    )
    placement = None
    reason = "Sections are unknown; a reviewer must identify musical placement."
    if intervals and percent >= 95:
        placement = Placement.THROUGHOUT
        reason = "Experimental throughout proposal from >=95% temporal coverage."
    elif expert and sections:
        labels = set(sections)
        if labels == {"chorus"}:
            placement = Placement.CHORUS
        elif (
            labels <= {"intro", "outro", "chorus"}
            and "chorus" in labels
            and labels & {"intro", "outro"}
        ):
            placement = Placement.INTRO_CHORUS
        elif labels <= {"intro", "outro"}:
            placement = Placement.INTRO_OUTRO
        elif labels == {"verse"}:
            placement = Placement.VERSES
        reason = "Proposed from expert-supplied section labels; verify final six-class choice."
    return Classification(
        placement=placement,
        coverage_category=category,
        source="expert_sections" if expert else "experimental_coverage",
        review_required=True,
        reason=reason,
    )
