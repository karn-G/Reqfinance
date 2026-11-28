let projectId = null;
let projectHasRequirements = false;
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
function toast(message) { const node = $("#toast"); node.textContent = message; node.classList.add("show"); setTimeout(() => node.classList.remove("show"), 3200); }
async function request(url, options = {}) { const response = await fetch(url, options); if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "Request failed"); } return response.json(); }
function displayDocuments(documents, rag) { $("#documentList").innerHTML = documents.map((doc) => `<div class="doc-row"><strong>${escapeHtml(doc.name)}</strong><small>${doc.chunks} processed evidence chunks</small></div>`).join(""); $("#ragSummary").innerHTML = `<span>${escapeHtml(rag.vector_database)}</span><span>${escapeHtml(rag.embedding_model)}</span><span>${rag.indexed_chunks} vectors indexed</span>`; $("#documentsPanel").classList.remove("is-hidden"); }
async function refreshSavedProjects() {
  const list = $("#savedProjects");
  try {
    const result = await request("/api/projects");
    list.innerHTML = result.projects.length ? result.projects.map((project) => `<div class="saved-project"><div><strong>${escapeHtml(project.functionality)}</strong><br><small>${project.requirement_count} requirement(s) · ${project.document_count} source(s) · ${escapeHtml(new Date(project.created_at).toLocaleDateString())}</small></div><button type="button" class="open-saved-project" data-id="${escapeHtml(project.id)}">Open</button></div>`).join("") : "<p class=\"muted\">No saved projects yet. Create a finance project to begin.</p>";
    list.querySelectorAll(".open-saved-project").forEach((button) => button.addEventListener("click", () => openSavedProject(button.dataset.id)));
  } catch (error) {
    list.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}
async function openSavedProject(id) {
  try {
    const project = await request(`/api/projects/${id}`);
    projectId = project.id;
    projectHasRequirements = project.requirements.length > 0;
    $("#functionality").value = project.functionality;
    $("#projectState").textContent = "Saved project opened";
    $("#newProjectButton").classList.remove("is-hidden");
    $("#exportLink").href = `/api/projects/${projectId}/export`;
    $("#reportLink").href = `/api/projects/${projectId}/report`;
    $("#exportLink").classList.remove("is-hidden");
    $("#reportLink").classList.remove("is-hidden");
    const rag = await request("/api/rag/status");
    const documents = project.documents.map((document) => ({ name: document.name, chunks: (document.chunks || []).length }));
    rag.indexed_chunks = documents.reduce((total, document) => total + document.chunks, 0);
    displayDocuments(documents, rag);
    $("#generateButton").textContent = projectHasRequirements ? "Regenerate drafts" : "Generate requirements";
    if (project.requirements.length) {
      displayRequirements(project);
      displayIssues(project.quality_issues);
      displayAgentAnalysis(project);
      $("#sdlcPanel").classList.remove("is-hidden");
      if (project.sdlc) displaySdlc(project.sdlc);
      else $("#sdlcResult").innerHTML = "";
    } else {
      $("#requirementsPanel").classList.add("is-hidden");
      $("#qualityPanel").classList.add("is-hidden");
      $("#agentsPanel").classList.add("is-hidden");
      $("#sdlcPanel").classList.add("is-hidden");
    }
    try {
      displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval`));
    } catch {
      displayRetrievedEvidence({ matches: [], count: 0 });
    }
    $(".saved-projects").open = false;
    toast("Saved project opened.");
  } catch (error) {
    toast(error.message);
  }
}
function displayRetrievedEvidence(result) { const list = $("#retrievalResults"); list.innerHTML = result.matches.length ? result.matches.map((match) => `<article class="retrieval-match"><div><span class="field-label">${escapeHtml(match.document_name)} / ${escapeHtml(match.id)}</span><p>${escapeHtml(match.text)}</p></div><strong>${Math.round(match.relevance * 100)}%</strong></article>`).join("") : "<p class=\"muted\">No matching chunks found.</p>"; $("#retrievalCount").textContent = `${result.count} match(es)`; }
function addRequirementEditors(project, list) {
  list.querySelectorAll(".requirement").forEach((card, index) => {
    const requirement = project.requirements[index];
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "quiet-button edit-toggle";
    editButton.textContent = "Modify draft";
    const editor = document.createElement("div");
    editor.className = "req-edit-form is-hidden";
    const statementLabel = document.createElement("label");
    statementLabel.textContent = "Requirement statement";
    const statement = document.createElement("textarea");
    statement.value = requirement.statement;
    statementLabel.append(statement);
    const criteriaLabel = document.createElement("label");
    criteriaLabel.textContent = "Acceptance criteria, one per line";
    const criteria = document.createElement("textarea");
    criteria.value = requirement.acceptance_criteria.join("\n");
    criteriaLabel.append(criteria);
    const actions = document.createElement("div");
    actions.className = "edit-actions";
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Save changes";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "quiet-button";
    cancel.textContent = "Cancel";
    actions.append(save, cancel);
    editor.append(statementLabel, criteriaLabel, actions);
    card.append(editButton, editor);
    editButton.addEventListener("click", () => editor.classList.toggle("is-hidden"));
    cancel.addEventListener("click", () => {
      statement.value = requirement.statement;
      criteria.value = requirement.acceptance_criteria.join("\n");
      editor.classList.add("is-hidden");
    });
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const updated = await request(`/api/projects/${projectId}/requirements/${requirement.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ statement: statement.value, acceptance_criteria: criteria.value.split(/\r?\n/) }),
        });
        displayRequirements(updated);
        displayIssues(updated.quality_issues);
        displayAgentAnalysis(updated);
        $("#sdlcResult").innerHTML = "";
        toast("Changes saved. The requirement needs review again, and SDLC analysis must be rerun.");
      } catch (error) {
        toast(error.message);
      } finally {
        save.disabled = false;
      }
    });
  });
}

function displayRequirements(project) {
  const list = $("#requirementsList");
  list.innerHTML = project.requirements.map((req) => `<article class="requirement"><div class="requirement-head"><div><span class="req-id">${escapeHtml(req.id)}</span><h3>${escapeHtml(req.statement)}</h3><div class="tags">${req.categories.map((category) => `<span class="tag">${escapeHtml(category)}</span>`).join("")}</div></div><select class="status" data-id="${escapeHtml(req.id)}" aria-label="Approval status for ${escapeHtml(req.id)}">${["Draft", "Needs review", "Approved", "Rejected"].map((status) => `<option ${req.approval_status === status ? "selected" : ""}>${status}</option>`).join("")}</select></div><div class="requirement-artifacts"><div><span class="field-label">Draft user story · confirm actor</span><p>${escapeHtml(req.user_story || "To be refined with stakeholders.")}</p></div><div><span class="field-label">Use case outline · confirm trigger and exceptions</span><p>${escapeHtml(req.use_case || "To be refined with stakeholders.")}</p></div></div><div class="requirement-grid"><div><span class="field-label">Business justification</span><p>${escapeHtml(req.business_justification)}</p></div><div><span class="field-label">Confidence / risk</span><p>${Math.round(req.confidence * 100)}% confidence · ${escapeHtml(req.risk_level)} risk · ${escapeHtml(req.priority)}</p></div><div><span class="field-label">Acceptance criteria</span><p>${req.acceptance_criteria.map(escapeHtml).join("<br>")}</p></div><div><span class="field-label">Reasoning</span><p>${escapeHtml(req.reasoning)}</p></div></div>${req.evidence.map((evidence) => `<div class="evidence"><span class="field-label">Evidence · ${escapeHtml(evidence.document_name)} / ${escapeHtml(evidence.chunk_id)}</span><p>${escapeHtml(evidence.excerpt)}</p></div>`).join("")}</article>`).join("");
  $("#requirementCount").textContent = `${project.requirements.length} draft(s)`;
  $("#requirementsPanel").classList.remove("is-hidden");
  list.querySelectorAll("select").forEach((select) => select.addEventListener("change", async () => {
    const data = new FormData();
    data.append("status", select.value);
    try {
      await request(`/api/projects/${projectId}/requirements/${select.dataset.id}/approval`, { method: "POST", body: data });
      document.querySelectorAll(".traceability-status").forEach((cell) => { if (cell.dataset.id === select.dataset.id) cell.textContent = select.value; });
      $("#sdlcResult").innerHTML = "";
      toast("Approval status recorded. Rerun SDLC analysis to refresh the recommendation.");
    } catch (error) {
      toast(error.message);
    }
  }));
  addRequirementEditors(project, list);
}
function displayIssues(issues) { $("#issuesList").innerHTML = issues.length ? issues.map((issue) => `<article class="issue"><div><span class="severity">${escapeHtml(issue.severity)}</span><p class="muted">${escapeHtml(issue.check)}</p></div><div><strong>${escapeHtml(issue.requirement_id || "Project")}</strong><p>${escapeHtml(issue.message)}</p><p class="recommendation">${escapeHtml(issue.recommendation)}</p></div></article>`).join("") : "<p class=\"muted\">No rule-based issues found. Human review is still required.</p>"; $("#issueCount").textContent = `${issues.length} issue(s)`; $("#qualityPanel").classList.remove("is-hidden"); }
function displayAgentAnalysis(project) { const reviews = project.agent_reviews || []; $("#agentReviews").innerHTML = reviews.map((review) => `<article class="agent-card"><div class="agent-card-head"><h3>${escapeHtml(review.agent)}</h3><span class="review-status ${review.status === "Complete" ? "complete" : "review"}">${escapeHtml(review.status)}</span></div><p>${escapeHtml(review.summary)}</p>${review.findings.length ? `<ul>${review.findings.map((finding) => `<li>${escapeHtml(finding)}</li>`).join("")}</ul>` : ""}${review.requirement_ids.length ? `<small>Linked: ${escapeHtml(review.requirement_ids.join(", "))}</small>` : ""}</article>`).join(""); const mappings = project.compliance_mappings || []; $("#complianceMappings").innerHTML = mappings.length ? `<div class="table-wrap"><table><thead><tr><th>Requirement</th><th>Candidate control area</th><th>Source evidence</th><th>Review</th></tr></thead><tbody>${mappings.map((mapping) => `<tr><td>${escapeHtml(mapping.requirement_id)}</td><td>${escapeHtml(mapping.control_area)}</td><td><strong>${escapeHtml(mapping.source_name)}</strong><br>${escapeHtml(mapping.source_excerpt)}</td><td>${escapeHtml(mapping.review_status)}</td></tr>`).join("")}</tbody></table></div>` : "<p class=\"muted\">No source-backed security, privacy, audit, or regulatory mappings were identified. Confirm applicable controls with the project owners.</p>"; const records = project.traceability || []; $("#traceabilityRecords").innerHTML = records.length ? `<div class="table-wrap"><table><thead><tr><th>Requirement</th><th>Source references</th><th>Confidence</th><th>Approval</th></tr></thead><tbody>${records.map((record) => `<tr><td>${escapeHtml(record.requirement_id)}</td><td>${record.source_references.map(escapeHtml).join("<br>") || "No linked source"}</td><td>${Math.round(record.confidence * 100)}%</td><td class="traceability-status" data-id="${escapeHtml(record.requirement_id)}">${escapeHtml(record.approval_status)}</td></tr>`).join("")}</tbody></table></div>` : "<p class=\"muted\">Traceability will appear after analysis.</p>"; $("#agentsPanel").classList.remove("is-hidden"); }
function displaySdlc(sdlc) { $("#sdlcResult").innerHTML = `<div class="sdlc-overview"><div><p class="eyebrow">Recommended model</p><h3>${escapeHtml(sdlc.recommended_sdlc)}</h3><p>${escapeHtml(sdlc.justification)}</p></div><div class="rankings">${sdlc.options.map((option) => `<div class="ranking"><span>${escapeHtml(option.name)}</span><div class="bar"><span style="width:${option.score}%"></span></div><strong>${option.score}%</strong></div>`).join("")}</div></div><div class="workflow"><p class="eyebrow">SDLC decision factors</p><div class="factor-grid">${sdlc.factors.map((factor) => `<div class="factor"><h4>${escapeHtml(factor.name)}</h4><strong>${escapeHtml(factor.value)}</strong><p>${escapeHtml(factor.rationale)}</p>${factor.requirement_ids.length ? `<small>Linked: ${escapeHtml(factor.requirement_ids.join(", "))}</small>` : ""}</div>`).join("")}</div></div><div class="workflow"><p class="eyebrow">Project-specific workflow</p><div class="workflow-grid">${sdlc.workflow.map((phase) => `<div class="phase"><h4>${escapeHtml(phase.phase)}</h4><p>${escapeHtml(phase.activities.join(" · "))}</p><p><strong>Gate:</strong> ${escapeHtml(phase.gate)}</p></div>`).join("")}</div></div>`; }
async function runFullAnalysis() {
  const button = $("#runAnalysisButton");
  const progress = $("#analysisProgress");
  button.disabled = true;
  try {
    progress.textContent = "Loading the preconfigured finance case study and indexing its source documents…";
    const selectedCase = $("#demoCaseSelect").value;
    const created = await request(`/api/demo-project?case_id=${encodeURIComponent(selectedCase)}`, { method: "POST" });
    projectId = created.project_id;
    projectHasRequirements = false;
    $("#functionality").value = created.functionality || $("#demoCaseSelect option:checked").textContent;
    $("#projectState").textContent = "Analysis in progress";
    $("#newProjectButton").classList.remove("is-hidden");
    $("#exportLink").href = `/api/projects/${projectId}/export`;
    $("#reportLink").href = `/api/projects/${projectId}/report`;
    $("#exportLink").classList.remove("is-hidden");
    $("#reportLink").classList.remove("is-hidden");
    displayDocuments(created.documents, created.rag);
    displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval`));

    progress.textContent = "Generating evidence-grounded requirements and running specialist reviews…";
    const project = await request(`/api/projects/${projectId}/requirements`, { method: "POST" });
    projectHasRequirements = true;
    $("#generateButton").textContent = "Regenerate drafts";
    displayRequirements(project);
    displayIssues(project.quality_issues);
    displayAgentAnalysis(project);

    progress.textContent = "Evaluating SDLC models and preparing the final recommendation…";
    const sdlc = await request(`/api/projects/${projectId}/sdlc`, { method: "POST" });
    displaySdlc(sdlc);
    $("#sdlcPanel").classList.remove("is-hidden");
    $("#projectState").textContent = "Analysis complete";
    progress.textContent = `Complete — ${project.requirements.length} requirements, ${project.quality_issues.length} quality findings, specialist reviews, traceability, and an SDLC recommendation are ready.`;
    toast("Financial analysis completed.");
    await refreshSavedProjects();
  } catch (error) {
    progress.textContent = `Analysis stopped: ${error.message}`;
    toast(error.message);
  } finally {
    button.disabled = false;
  }
}
async function loadDemoCases() {
  try {
    const result = await request("/api/demo-projects");
    const select = $("#demoCaseSelect");
    const current = select.value;
    select.innerHTML = result.projects.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
    select.value = result.projects.some((item) => item.id === current) ? current : "loan";
    const updateDescription = () => {
      const selected = result.projects.find((item) => item.id === select.value);
      $("#demoCaseDescription").textContent = selected?.description || "Select a preconfigured case study.";
      $("#functionality").value = selected?.name || "";
    };
    select.addEventListener("change", updateDescription);
    updateDescription();
  } catch (error) {
    toast(`Could not load project types: ${error.message}`);
  }
}
$("#runAnalysisButton").addEventListener("click", runFullAnalysis);
loadDemoCases();
$("#retrieveButton").addEventListener("click", async () => { if (!projectId) return; const button = $("#retrieveButton"); button.disabled = true; try { const query = $("#retrievalQuery").value.trim() || $("#functionality").value.trim(); displayRetrievedEvidence(await request(`/api/projects/${projectId}/retrieval?query=${encodeURIComponent(query)}`)); } catch (error) { toast(error.message); } finally { button.disabled = false; } });
$("#generateButton").addEventListener("click", async () => {
  if (!projectId) return;
  if (projectHasRequirements && !window.confirm("Regenerating replaces draft edits and approval decisions. Continue?")) return;
  const button = $("#generateButton");
  button.disabled = true;
  try {
    const project = await request(`/api/projects/${projectId}/requirements`, { method: "POST" });
    projectHasRequirements = true;
    button.textContent = "Regenerate drafts";
    displayRequirements(project);
    displayIssues(project.quality_issues);
    displayAgentAnalysis(project);
    $("#sdlcPanel").classList.remove("is-hidden");
    $("#sdlcResult").innerHTML = "";
    toast("Evidence-grounded drafts and specialist reviews are ready.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
$("#sdlcButton").addEventListener("click", async () => { if (!projectId) return; const button = $("#sdlcButton"); button.disabled = true; try { displaySdlc(await request(`/api/projects/${projectId}/sdlc`, { method: "POST" })); toast("SDLC recommendation generated. Human approval remains required."); } catch (error) { toast(error.message); } finally { button.disabled = false; } });
$("#newProjectButton").addEventListener("click", () => window.location.reload());
$(".saved-projects").addEventListener("toggle", () => { if ($(".saved-projects").open) refreshSavedProjects(); });
refreshSavedProjects();
