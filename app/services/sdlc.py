from __future__ import annotations

from app.schemas import Category, Requirement, SdlcFactor, SdlcOption, SdlcRecommendation, WorkflowPhase


def _requirement_ids(requirements: list[Requirement], categories: set[Category]) -> list[str]:
    return [requirement.id for requirement in requirements if categories & set(requirement.categories)]


def _factor(name: str, score: int, value: str, rationale: str, requirement_ids: list[str] | None = None) -> SdlcFactor:
    return SdlcFactor(name=name, score=score, value=value, rationale=rationale, requirement_ids=requirement_ids or [])


def _score(base: int, adjustments: list[tuple[bool, int]]) -> int:
    return max(0, min(100, base + sum(amount for applies, amount in adjustments if applies)))


def recommend(requirements: list[Requirement]) -> SdlcRecommendation:
    """Rank requested SDLC models from requirement signals without inventing project facts."""
    categories = {category for requirement in requirements for category in requirement.categories}
    needs_review = sum(requirement.approval_status != "Approved" for requirement in requirements)
    measurable = sum(bool(requirement.acceptance_criteria) and not any("reviewer" in item.lower() for item in requirement.acceptance_criteria) for requirement in requirements)
    high_risk = sum(requirement.risk_level == "High" for requirement in requirements)
    security_or_compliance = {Category.SECURITY, Category.PRIVACY, Category.REGULATORY, Category.AUDIT}
    risk_ids = _requirement_ids(requirements, security_or_compliance)
    integration_ids = _requirement_ids(requirements, {Category.INTEGRATION, Category.DATA})
    stakeholder_ids = _requirement_ids(requirements, {Category.STAKEHOLDER, Category.USABILITY, Category.BUSINESS})

    stability_score = 2 if needs_review else 4
    clarity_score = 4 if measurable == len(requirements) else 2 if measurable == 0 else 3
    risk_score = 5 if high_risk or risk_ids else 3
    complexity_score = 4 if integration_ids else 2
    early_prototype_score = 4 if clarity_score <= 2 or complexity_score >= 4 else 3
    time_score = 3
    involvement_score = 4 if stakeholder_ids else 3
    change_score = 3
    iterative_score = 4 if clarity_score <= 2 or needs_review else 3
    risk_analysis_score = 5 if risk_score >= 5 or complexity_score >= 4 else 3

    factors = [
        _factor("Requirement stability", stability_score, "Needs validation" if needs_review else "Baseline approved", "Draft or unapproved requirements indicate that stability has not yet been demonstrated." if needs_review else "All requirements have an explicit approval status.", [requirement.id for requirement in requirements if requirement.approval_status != "Approved"]),
        _factor("Requirement clarity", clarity_score, "Low" if clarity_score <= 2 else "Moderate" if clarity_score == 3 else "High", "Measured from the presence of concrete, non-placeholder acceptance criteria.", [requirement.id for requirement in requirements if not requirement.acceptance_criteria or any("reviewer" in item.lower() for item in requirement.acceptance_criteria)]),
        _factor("Risk", risk_score, "High" if risk_score >= 5 else "Medium", "Derived from stated high risk and security, privacy, regulatory, or audit classifications.", risk_ids),
        _factor("Complexity", complexity_score, "High" if complexity_score >= 4 else "Low", "Integration and data-management requirements increase coordination and technical complexity.", integration_ids),
        _factor("Need for early prototype", early_prototype_score, "Likely" if early_prototype_score >= 4 else "Confirm with stakeholders", "Unclear requirements or integration complexity make early learning and validation valuable."),
        _factor("Time constraints", time_score, "Not evidenced", "No schedule or deadline evidence is available in the generated requirements; confirm this with the project sponsor."),
        _factor("Customer involvement", involvement_score, "Evidenced" if stakeholder_ids else "Not evidenced", "Derived only from business, stakeholder, or usability requirements; otherwise this must be confirmed.", stakeholder_ids),
        _factor("Frequency of changes", change_score, "Not evidenced", "Requirement documents do not establish the expected change rate; confirm with product and business stakeholders."),
        _factor("Need for iterative development", iterative_score, "Likely" if iterative_score >= 4 else "Confirm with stakeholders", "Unapproved or unclear requirements benefit from repeated review and validation cycles."),
        _factor("Need for risk analysis", risk_analysis_score, "High" if risk_analysis_score >= 5 else "Medium", "Security/compliance concerns or complex integration warrant explicit risk analysis.", sorted(set(risk_ids + integration_ids))),
    ]

    stable = stability_score >= 4
    clear = clarity_score >= 4
    unclear = clarity_score <= 2
    high_risk_or_analysis = risk_score >= 5 or risk_analysis_score >= 5
    complex_project = complexity_score >= 4
    prototype_helpful = early_prototype_score >= 4
    iterative = iterative_score >= 4
    customer_available = bool(stakeholder_ids)
    time_pressure = time_score >= 4

    # Use requirement content and category distribution to avoid a generic
    # "financial project = Spiral" outcome. These are heuristic advisory scores,
    # not claims about a project's domain or regulatory obligations.
    statements = " ".join(requirement.statement.lower() for requirement in requirements)
    category_counts = {
        category: sum(category in requirement.categories for requirement in requirements)
        for category in Category
    }
    security_count = sum(category_counts[c] for c in {Category.SECURITY, Category.PRIVACY})
    governance_count = sum(category_counts[c] for c in {Category.REGULATORY, Category.AUDIT})
    delivery_count = sum(category_counts[c] for c in {Category.PERFORMANCE, Category.AVAILABILITY, Category.OPERATIONAL})
    user_change_count = sum(category_counts[c] for c in {Category.STAKEHOLDER, Category.USABILITY, Category.BUSINESS})
    transaction_signal = any(word in statements for word in ("transaction", "payment", "settlement", "reconciliation", "ledger"))
    detection_signal = any(word in statements for word in ("detect", "anomal", "fraud", "alert", "monitor"))
    workflow_signal = any(word in statements for word in ("claim", "case", "application", "review", "approval"))
    uncertain_scope = unclear or needs_review > max(1, len(requirements) // 3)
    strong_risk = high_risk >= max(2, len(requirements) // 3)
    strong_governance = governance_count >= 2
    strong_delivery = delivery_count >= 2
    strong_user_feedback = user_change_count >= 2

    options = [
        SdlcOption(name="Waterfall", score=_score(38, [(stable, 24), (clear, 20), (not iterative, 8), (strong_governance, 5), (unclear, -22), (strong_delivery, -5)]), suitability="Best when requirements are stable, fully specified, and changes are controlled."),
        SdlcOption(name="V-Model", score=_score(40, [(stable, 15), (clear, 16), (strong_governance, 24), (high_risk_or_analysis, 8), (unclear, -16)]), suitability="Best when requirements need explicit verification and validation evidence at each stage."),
        SdlcOption(name="Iterative", score=_score(42, [(iterative, 18), (uncertain_scope, 18), (prototype_helpful, 10), (strong_user_feedback, 8), (strong_governance, 3)]), suitability="Best when the solution can be refined through repeated cycles based on evaluation and feedback."),
        SdlcOption(name="Incremental", score=_score(45, [(iterative, 15), (complex_project, 14), (prototype_helpful, 8), (customer_available, 8), (time_pressure, 8), (transaction_signal, 5), (workflow_signal, 5)]), suitability="Best when value can be divided into validated, independently testable increments."),
        SdlcOption(name="Spiral", score=_score(30, [(strong_risk, 22), (complex_project, 10), (uncertain_scope, 8), (risk_score >= 5 and complexity_score >= 4 and strong_risk, 12), (not strong_risk, -12), (not complex_project, -8)]), suitability="Best when substantial project risk and uncertainty justify repeated risk-analysis and risk-reduction cycles."),
        SdlcOption(name="RAD (Rapid Application Development)", score=_score(38, [(time_pressure, 25), (customer_available, 15), (iterative, 10), (strong_risk, -12), (complex_project, -8), (strong_governance, -8)]), suitability="Best for time-boxed delivery with frequent user feedback and modular, lower-risk scope."),
        SdlcOption(name="Scrum", score=_score(40, [(iterative, 14), (strong_user_feedback, 18), (uncertain_scope, 10), (customer_available, 8), (strong_governance, -2)]), suitability="Agile framework best when a product owner and team can plan work in short, fixed-length sprints and review increments regularly."),
        SdlcOption(name="Extreme Programming (XP)", score=_score(38, [(iterative, 12), (strong_user_feedback, 10), (uncertain_scope, 8), (security_count >= 1, 4), (strong_governance, -4)]), suitability="Agile method best for teams using frequent releases, continuous testing, pair programming, and close customer collaboration."),
    ]
    options.sort(key=lambda option: option.score, reverse=True)
    choice = options[0].name
    factor_summary = ", ".join(f"{factor.name.lower()} is {factor.value.lower()}" for factor in factors[:5])
    return SdlcRecommendation(
        recommended_sdlc=choice,
        factors=factors,
        options=options,
        justification=f"{choice} has the highest transparent score because {factor_summary}. Factors marked 'Not evidenced' are deliberately neutral and require stakeholder confirmation before the SDLC is approved.",
        workflow=[
            WorkflowPhase(phase="Validate requirements", activities=["Resolve ambiguity and possible conflicts", "Confirm business rules, data handling, and exceptions", "Link each baseline item to approved evidence"], roles=["Business analyst", "Product owner", "Compliance officer"], deliverables=["Reviewed requirements", "Traceability matrix", "Open-issues register"], gate="Business and compliance owners approve the baseline"),
            WorkflowPhase(phase="Design and assess risk", activities=["Review data flows and trust boundaries", "Threat-model payment, identity, and customer-data paths", "Map evidence to candidate controls"], roles=["Architect", "Security lead", "Privacy lead", "Risk owner"], deliverables=["Architecture and threat model", "Risk register", "Control review record"], gate="Architecture, security, and compliance review"),
            WorkflowPhase(phase="Build and verify", activities=["Implement approved scope in controlled increments", "Run code, dependency, and security checks", "Test transaction integrity, access rules, and acceptance criteria"], roles=["Developers", "QA", "Security engineer", "Business tester"], deliverables=["Release candidate", "Test and security evidence", "Updated traceability"], gate="Quality and control evidence accepted by accountable owners"),
            WorkflowPhase(phase="Release and monitor", activities=["Approve deployment and rollback readiness", "Record release and control sign-offs", "Monitor service, incidents, and requirement changes"], roles=["Operations", "Product owner", "Security operations", "Compliance officer"], deliverables=["Release record", "Monitoring and audit evidence", "Updated risk assessment"], gate="Production-readiness and change-control approval"),
        ],
    )
