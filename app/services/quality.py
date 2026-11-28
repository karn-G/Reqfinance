from __future__ import annotations

import re

from app.schemas import QualityIssue, Requirement


VAGUE = {
    "fast", "secure", "easy", "appropriate", "efficient", "robust",
    "user-friendly", "adequate",
}

# Terms that indicate a requirement may affect money movement, identity,
# credentials, sensitive personal/financial data, or important access decisions.
_HIGH_IMPACT_TERMS = {
    "payment", "payments", "transaction", "transactions", "refund", "refunds",
    "cardholder", "card", "bank", "banking", "loan", "lending", "credit",
    "account", "accounts", "authentication", "authenticate", "credential",
    "credentials", "identity", "verification", "verify", "customer data",
    "personal data", "financial data", "fraud", "transfer", "transfers",
    "settlement", "dispute", "claim", "claims", "beneficiary", "payout",
}
_MEDIUM_IMPACT_TERMS = {
    "document", "documents", "record", "records", "audit", "reporting",
    "approval", "approver", "role", "roles", "access", "retention",
    "privacy", "compliance", "regulatory", "sensitive", "consent",
}


def _polarity(statement: str) -> str | None:
    text = statement.lower()
    negative = bool(re.search(r"\b(?:must not|shall not|cannot|prohibit(?:ed)?|disallow|disable|deny)\b", text))
    if negative:
        return "negative"
    positive = bool(re.search(r"\b(?:must|shall|allow|enable|permit|support)\b", text))
    return "positive" if positive else None


def _missing_control_severity(req: Requirement) -> str:
    """Estimate review priority when a requirement has no explicit control category.

    This is a triage heuristic, not a finding that a vulnerability or breach exists.
    """
    text = f"{req.statement} {req.business_justification}".lower()
    categories = {category.value for category in req.categories}

    if req.risk_level == "High":
        return "High"

    if any(term in text for term in _HIGH_IMPACT_TERMS):
        return "High"

    if req.risk_level == "Medium" or any(term in text for term in _MEDIUM_IMPACT_TERMS):
        return "Medium"

    if categories.intersection({"Integration", "Data management", "Audit / reporting"}):
        return "Medium"

    return "Low"


def analyse(requirements: list[Requirement]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for req in requirements:
        statement = req.statement.lower()
        if any(re.search(rf"\b{re.escape(word)}\b", statement) for word in VAGUE):
            issues.append(QualityIssue(
                id=f"QI-{len(issues)+1:03d}", requirement_id=req.id,
                check="Ambiguity", severity="Medium",
                message="The requirement contains a qualitative term without a measurable threshold.",
                recommendation="Define an observable metric, limit, or acceptance test.",
            ))
        if not req.evidence:
            issues.append(QualityIssue(
                id=f"QI-{len(issues)+1:03d}", requirement_id=req.id,
                check="Missing evidence", severity="High",
                message="No source evidence is attached.",
                recommendation="Link an approved source or mark the item as an explicit stakeholder decision.",
            ))
        if not req.acceptance_criteria or any("Human reviewer" in item for item in req.acceptance_criteria):
            issues.append(QualityIssue(
                id=f"QI-{len(issues)+1:03d}", requirement_id=req.id,
                check="Lack of testability", severity="Medium",
                message="Acceptance criteria are absent or not yet measurable.",
                recommendation="Add pass/fail criteria, test data, and expected outcome.",
            ))

        has_control_category = any(
            category.value in {"Security", "Privacy", "Regulatory"}
            for category in req.categories
        )
        if not has_control_category:
            severity = _missing_control_severity(req)
            issues.append(QualityIssue(
                id=f"QI-{len(issues)+1:03d}", requirement_id=req.id,
                check="Missing security or compliance requirements", severity=severity,
                message=(
                    "This item has no linked security, privacy, or regulatory control. "
                    "The severity is a review-priority estimate based on requirement context, not a confirmed vulnerability."
                ),
                recommendation="Confirm whether a control is not applicable or add an evidence-backed control.",
            ))

    for index, first in enumerate(requirements):
        normalized = set(re.findall(r"[a-z]{5,}", first.statement.lower()))
        for second in requirements[index + 1:]:
            other = set(re.findall(r"[a-z]{5,}", second.statement.lower()))
            if normalized and len(normalized & other) / len(normalized | other) > 0.72:
                issues.append(QualityIssue(
                    id=f"QI-{len(issues)+1:03d}", requirement_id=first.id,
                    check="Duplication", severity="Medium",
                    message=f"Potential overlap with {second.id}.",
                    recommendation="Merge, differentiate scope, or link the requirements.",
                ))
            first_polarity = _polarity(first.statement)
            second_polarity = _polarity(second.statement)
            if normalized and first_polarity and second_polarity and first_polarity != second_polarity:
                shared = len(normalized & other) / max(1, len(normalized | other))
                if shared > 0.4:
                    issues.append(QualityIssue(
                        id=f"QI-{len(issues)+1:03d}", requirement_id=first.id,
                        check="Potential conflict", severity="High",
                        message=f"{first.id} and {second.id} use opposing obligation language over similar terms.",
                        recommendation="Ask the requirement owners to reconcile the scope and record the approved decision.",
                    ))
    return issues
