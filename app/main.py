from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.schemas import Project, RequirementRevision
from app.services.documents import chunk_text, extract_text, mask_sensitive
from app.services.agents import coordinate_reviews
from app.services.generator import classify, generate_evidence_drafts
from app.services.llm import enabled as llm_enabled, generate_requirements as generate_llm_requirements
from app.services.quality import analyse
from app.services.reports import build_project_report
from app.services.rag import RagConfigurationError, VectorStore, provider_configured
from app.services.sdlc import recommend
from app.services.storage import ProjectStore

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
store = ProjectStore()
vector_store = VectorStore()


@asynccontextmanager
async def lifespan(_: FastAPI):
    print("\n" + "=" * 56)
    print("  ReqFinance is running")
    print("  App:      http://reqfinance.localhost:8000")
    print("  API docs: http://reqfinance.localhost:8000/docs")
    print("  RAG:      ChromaDB + OpenAI-compatible embeddings")
    print("  Storage:  local JSON project data and ChromaDB vectors")
    print("  Stop:     press Ctrl+C")
    print("=" * 56 + "\n")
    yield
    print("ReqFinance stopped.")


app = FastAPI(title="ReqFinance | Financial Requirements Engineering", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def audit(project: Project, action: str, detail: str) -> None:
    project.audit_log.append({"at": datetime.now(timezone.utc).isoformat(), "action": action, "detail": detail})


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "templates" / "index.html")


@app.get("/api/rag/status")
def rag_status() -> JSONResponse:
    return JSONResponse({
        **vector_store.configuration(),
        "embedding_provider_configured": provider_configured(),
        "generation_mode": "LLM generation with citation validation" if llm_enabled() else "Evidence-only drafts until LLM_API_KEY is configured",
    })


@app.get("/api/projects")
def list_projects() -> JSONResponse:
    return JSONResponse({"projects": store.list_summaries()})


@app.post("/api/projects")
async def create_project(
    functionality: str = Form(...),
    stakeholder_input: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    functionality = functionality.strip()
    if len(functionality) < 3:
        raise HTTPException(422, "Enter a financial functionality of at least three characters.")
    try:
        answers = json.loads(stakeholder_input)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Stakeholder answers could not be processed.") from exc
    if not isinstance(answers, dict):
        raise HTTPException(422, "Stakeholder answers must be a structured set of responses.")
    answers = {str(question): str(answer).strip() for question, answer in answers.items() if str(answer).strip()}
    uploads = [upload for upload in files if upload.filename]
    if not answers and not uploads:
        raise HTTPException(422, "Answer at least one stakeholder question or upload a supporting document.")
    documents = []
    if answers:
        interview_text = "\n".join(f"{question}: {answer}" for question, answer in answers.items())
        masked_text = mask_sensitive(interview_text)
        documents.append({"id": "DOC-001", "name": "Stakeholder interview", "chunks": [chunk.__dict__ for chunk in chunk_text(masked_text)]})
    for upload in uploads:
        content = await upload.read()
        if len(content) > 5_000_000:
            raise HTTPException(413, f"{upload.filename} exceeds the 5 MB prototype limit.")
        try:
            text = mask_sensitive(extract_text(upload.filename, content))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not text.strip():
            raise HTTPException(422, f"{upload.filename} contains no extractable text.")
        doc_id = f"DOC-{len(documents)+1:03d}"
        documents.append({"id": doc_id, "name": upload.filename, "chunks": [chunk.__dict__ for chunk in chunk_text(text)]})
    project = Project(id=uuid4().hex[:12], functionality=functionality, created_at=datetime.now(timezone.utc), documents=documents)
    try:
        indexed_chunks = vector_store.index(project.id, documents)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    audit(project, "sources_recorded", f"Stored {len(documents)} masked source(s): {len(answers)} stakeholder response(s) and {len(uploads)} uploaded document(s).")
    audit(project, "rag_indexed", f"Indexed {indexed_chunks} source chunk(s) in ChromaDB.")
    store.save(project)
    return JSONResponse({
        "project_id": project.id,
        "documents": [{"id": doc["id"], "name": doc["name"], "chunks": len(doc["chunks"])} for doc in documents],
        "rag": {**vector_store.configuration(), "indexed_chunks": indexed_chunks},
    })


DEMO_CASES = {
    "loan": {
        "name": "Loan Application and Approval",
        "description": "Applicant onboarding, identity checks, eligibility, underwriting, and approval workflow.",
        "brief": "Business objective: Manage customer loan applications, verify applicant information, assess eligibility, and support authorised approval or rejection decisions.\nUsers and roles: Applicants submit applications and track status; loan officers review applications and documents; managers make approval or rejection decisions; administrators manage users and system settings.\nWorkflow: Capture applicant details, requested loan amount, repayment term, consent, and supporting documents; verify identity; assess eligibility; route exceptions or missing information for human review; record the decision and notify the applicant.\nKnown controls: Role-based access, protected financial documents, audit records, policy-version traceability, and human review for missing or failed verification data.",
        "sources": ["loan_origination_controls.txt", "digital_onboarding_policy.txt"],
    },
    "banking": {
        "name": "Digital Banking System",
        "description": "Customer accounts, secure access, balances, transaction history, and money transfers.",
        "brief": "Business objective: Provide customers with secure digital access to banking account information and transfer services.\nUsers and roles: Customers view their own accounts and initiate transfers; operations staff investigate exceptions; administrators manage access and configuration.\nWorkflow: Authenticate the customer, display authorised accounts, validate transfer details, confirm the transaction, and provide a reference and status.\nKnown controls: Multi-factor authentication for sensitive actions, customer data isolation, audit logging, notifications, duplicate-transfer prevention, and human review of exceptions.",
        "sources": ["digital_banking_accounts.txt", "digital_banking_transfers.txt"],
    },
    "payments": {
        "name": "Payment Gateway",
        "description": "Merchant API payments, transaction status, duplicate prevention, reconciliation, and disputes.",
        "brief": "Business objective: Process merchant payment requests and provide traceable transaction outcomes.\nUsers and roles: Merchants submit payment requests and view statuses; payment operations staff reconcile transactions and manage exceptions; authorised reviewers handle disputes.\nWorkflow: Authenticate merchant, validate request, process or route payment, return a transaction reference, and reconcile settlement records.\nKnown controls: API authentication, idempotency, sensitive-data protection, audit trails, role-restricted refunds, and exception handling.",
        "sources": ["payment_gateway_processing.txt", "payment_gateway_reconciliation.txt"],
    },
    "fraud": {
        "name": "Fraud Detection System",
        "description": "Risk indicators, transaction alerts, investigator queues, case management, and audit history.",
        "brief": "Business objective: Identify potentially suspicious activity and support controlled investigation and disposition.\nUsers and roles: Fraud analysts review alerts and manage cases; senior investigators handle escalations; administrators maintain approved rules.\nWorkflow: Evaluate eligible events, create prioritised alerts, assign investigations, record evidence and disposition, and report outcomes.\nKnown controls: Versioned rules, restricted case access, audit history, escalation, and human review before irreversible adverse action.",
        "sources": ["fraud_detection_monitoring.txt", "fraud_case_management.txt"],
    },
    "insurance": {
        "name": "Insurance Claims Management",
        "description": "Claim submission, document validation, assessment, approval, escalation, and claimant updates.",
        "brief": "Business objective: Manage insurance claims from initial submission through assessment and decision.\nUsers and roles: Policyholders submit claims and view status; claims assessors review evidence; supervisors approve escalated decisions; administrators manage workflow configuration.\nWorkflow: Capture claim details, validate required information, assign an assessor, record findings and rationale, and notify the claimant.\nKnown controls: Role-based document access, auditable decisions, escalation for authority limits, and requests for missing information.",
        "sources": ["insurance_claims_intake.txt", "insurance_claims_assessment.txt"],
    },
}


@app.get("/api/demo-projects")
def list_demo_projects() -> JSONResponse:
    return JSONResponse({"projects": [{"id": key, "name": value["name"], "description": value["description"]} for key, value in DEMO_CASES.items()]})


@app.post("/api/demo-project")
def create_preconfigured_demo_project(case_id: str = "loan") -> JSONResponse:
    """Create a fictional preconfigured finance case study from bundled sample sources."""
    case = DEMO_CASES.get(case_id)
    if case is None:
        raise HTTPException(404, "Unknown demonstration project type.")
    functionality = case["name"]
    brief = ("Preconfigured demonstration project brief (fictional). Replace with approved, jurisdiction-specific policies before real use.\n" + case["brief"] + "\nAssumptions: This case study is illustrative only. Applicable thresholds, jurisdictional obligations, service levels, retention periods, and production controls require owner confirmation.\n")
    source_files = [("project_brief.txt", brief)]
    for filename in case["sources"]:
        source_path = ROOT.parent / "sample_data" / filename
        if not source_path.is_file():
            raise HTTPException(500, f"Bundled source file is missing: {filename}")
        source_files.append((filename, source_path.read_text(encoding="utf-8")))
    documents = []
    for index, (name, content) in enumerate(source_files, start=1):
        masked = mask_sensitive(content)
        documents.append({"id": f"DOC-{index:03d}", "name": name, "chunks": [chunk.__dict__ for chunk in chunk_text(masked)]})
    project = Project(id=uuid4().hex[:12], functionality=functionality, created_at=datetime.now(timezone.utc), documents=documents)
    try:
        indexed_chunks = vector_store.index(project.id, documents)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    audit(project, "sources_recorded", f"Loaded {len(documents)} fictional demonstration sources for {functionality}; no interview input required.")
    audit(project, "rag_indexed", f"Indexed {indexed_chunks} preconfigured source chunk(s) in ChromaDB.")
    store.save(project)
    return JSONResponse({
        "project_id": project.id,
        "functionality": functionality,
        "documents": [{"id": doc["id"], "name": doc["name"], "chunks": len(doc["chunks"])} for doc in documents],
        "rag": {**vector_store.configuration(), "indexed_chunks": indexed_chunks},
    })

@app.get("/api/projects/{project_id}/retrieval")
def retrieve_evidence(project_id: str, query: str | None = None) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    search_query = (query or project.functionality).strip()
    if len(search_query) < 3:
        raise HTTPException(422, "Enter a retrieval query of at least three characters.")
    try:
        evidence = vector_store.retrieve(project.id, search_query)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    return JSONResponse({"query": search_query, "matches": evidence, "count": len(evidence)})


@app.post("/api/projects/{project_id}/requirements")
def generate_requirements(project_id: str) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    try:
        evidence = vector_store.retrieve(project.id, project.functionality)
    except RagConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not evidence:
        raise HTTPException(422, "No retrievable evidence was found in the uploaded documents.")
    regenerating = bool(project.requirements)
    generation_mode = "evidence-only"
    if llm_enabled():
        try:
            project.requirements = generate_llm_requirements(project.functionality, evidence)
            generation_mode = "LLM-assisted"
        except (RuntimeError, ValueError) as exc:
            project.requirements = generate_evidence_drafts(project.functionality, evidence)
            audit(project, "llm_fallback", str(exc))
    else:
        project.requirements = generate_evidence_drafts(project.functionality, evidence)
    project.quality_issues = analyse(project.requirements)
    project.agent_reviews, project.compliance_mappings, project.traceability = coordinate_reviews(
        project.functionality, project.requirements, project.quality_issues
    )
    project.sdlc = None
    action = "requirements_regenerated" if regenerating else "requirements_generated"
    audit(project, action, f"Generated {len(project.requirements)} {generation_mode} RAG-grounded draft requirement(s).")
    for review in project.agent_reviews:
        audit(project, "specialist_review_completed", f"{review.agent}: {review.summary}")
    store.save(project)
    return JSONResponse(project.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/requirements/{requirement_id}/approval")
def update_approval(project_id: str, requirement_id: str, status: str = Form(...)) -> JSONResponse:
    if status not in {"Approved", "Rejected", "Needs review", "Draft"}:
        raise HTTPException(422, "Invalid approval status.")
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    requirement = next((item for item in project.requirements if item.id == requirement_id), None)
    if not requirement:
        raise HTTPException(404, "Requirement not found.")
    requirement.approval_status = status
    traceability = next((item for item in project.traceability if item.requirement_id == requirement_id), None)
    if traceability:
        traceability.approval_status = status
    project.sdlc = None
    audit(project, "requirement_approval_updated", f"{requirement_id} marked {status}.")
    store.save(project)
    return JSONResponse(requirement.model_dump(mode="json"))


@app.put("/api/projects/{project_id}/requirements/{requirement_id}")
def revise_requirement(project_id: str, requirement_id: str, revision: RequirementRevision) -> JSONResponse:
    statement = revision.statement.strip()
    if len(statement) < 12:
        raise HTTPException(422, "Write a requirement statement with at least 12 characters.")
    criteria = [criterion.strip() for criterion in revision.acceptance_criteria if criterion.strip()]
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    requirement = next((item for item in project.requirements if item.id == requirement_id), None)
    if not requirement:
        raise HTTPException(404, "Requirement not found.")
    requirement.statement = statement
    requirement.categories = classify(statement)
    requirement.acceptance_criteria = criteria
    requirement.approval_status = "Needs review"
    requirement.reasoning = "Edited by a human reviewer. Recheck the linked evidence and quality findings before approval."
    project.quality_issues = analyse(project.requirements)
    project.agent_reviews, project.compliance_mappings, project.traceability = coordinate_reviews(
        project.functionality, project.requirements, project.quality_issues
    )
    project.sdlc = None
    audit(project, "requirement_revised", f"{requirement_id} edited by a human reviewer and returned to Needs review.")
    store.save(project)
    return JSONResponse(project.model_dump(mode="json"))


@app.post("/api/projects/{project_id}/sdlc")
def sdlc_analysis(project_id: str) -> JSONResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    if not project.requirements:
        raise HTTPException(422, "Generate requirements before SDLC analysis.")
    project.sdlc = recommend(project.requirements)
    audit(project, "sdlc_analysed", f"Recommended {project.sdlc.recommended_sdlc}; human approval remains required.")
    store.save(project)
    return JSONResponse(project.sdlc.model_dump(mode="json"))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> JSONResponse:
    try:
        return JSONResponse(store.get(project_id).model_dump(mode="json"))
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> JSONResponse:
    try:
        return JSONResponse(store.export(store.get(project_id)), headers={"Content-Disposition": f'attachment; filename="reqfinance-{project_id}.json"'})
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc


@app.get("/api/projects/{project_id}/report")
def export_project_report(project_id: str) -> PlainTextResponse:
    try:
        project = store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Project not found.") from exc
    return PlainTextResponse(
        build_project_report(project),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="reqfinance-{project_id}-srs.md"'},
    )
