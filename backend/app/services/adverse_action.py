from datetime import UTC, datetime

from app.schemas.adverse_action import AdverseActionNotice, PrincipalReason
from app.schemas.decision import Band, DecisionOutcome, DecisionResponse

ECOA_NOTICE = (
    "The Federal Equal Credit Opportunity Act prohibits creditors from discriminating against credit applicants "
    "on the basis of race, color, religion, national origin, sex, marital status, age (provided the applicant has "
    "the capacity to enter into a binding contract); because all or part of the applicant's income derives from any "
    "public assistance program; or because the applicant has in good faith exercised any right under the Consumer "
    "Credit Protection Act."
)
RIGHT_TO_REASONS = (
    "The principal reasons for this decision are listed above. You may request additional information about these "
    "reasons within 60 days of this notice."
)


class NotAdverseAction(Exception):
    pass


def build_notice(decision: DecisionResponse) -> AdverseActionNotice:
    """Reg B notice for a declined application: up to 4 principal reasons, applicant-facing text only."""
    if decision.band != Band.DECLINE:
        raise NotAdverseAction(f"no adverse action: application status is {decision.decision.value}")
    ranked = sorted(decision.reason_codes, key=lambda r: r.contribution, reverse=True)[:4]
    return AdverseActionNotice(
        decision_id=decision.decision_id,
        application_id=decision.application_id,
        action_taken=DecisionOutcome.DECLINED,
        notice_date=datetime.now(UTC),
        principal_reasons=[
            PrincipalReason(rank=i, reason=r.reason, ecoa_category=r.ecoa_category)
            for i, r in enumerate(ranked, start=1)
        ],
        ecoa_notice=ECOA_NOTICE,
        right_to_request_reasons=RIGHT_TO_REASONS,
    )
