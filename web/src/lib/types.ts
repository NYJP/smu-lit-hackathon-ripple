// The shared shape of everything the API returns.
//
// These used to be redeclared inline in whichever component happened to need
// them, which drifted: `Impact` had two incompatible shapes and `Job` had
// three. Severity in particular was always typed `string`, so no switch over
// it could ever be checked. Declare a domain type here and import it.
//
// Mirrors api/models.py and the router response shapes (PRD sections 5.5 / 9).

export type Role = "admin" | "member";

/** GET /users item — api/models.py UserOut. */
export interface RosterUser {
  id: string;
  display_name: string;
  role: Role;
  document_count: number;
  last_seen_at: string | null;
}

/** GET /users — api/models.py UsersListOut. */
export interface UsersListResponse {
  items: RosterUser[];
}

/** The user embedded in POST /auth/session and GET /auth/me — api/models.py MeUser. */
export interface MeUser {
  id: string;
  display_name: string;
  role: Role;
}

/** GET /auth/me — api/models.py MeOut. */
export interface MeResponse {
  user: MeUser;
}

/** POST /auth/session — api/models.py SessionOut. */
export interface SessionResponse {
  user: MeUser;
}

/** The section 9 error envelope, produced by every 4xx/5xx. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
  };
}

// ---------------------------------------------------------------- severity --

/**
 * What the model stored, verbatim (PRD section 8.3). The prompt is bound to
 * these four words; never widen this union without changing the prompt.
 */
export type ImpactLevel = "high" | "medium" | "low" | "none";

/**
 * What a screen displays. `critical` is derived from a stored `high` whose
 * deadline is inside 30 days — see api/services/severity.py, which is the
 * only place the escalation happens.
 */
export type Severity = "critical" | "high" | "medium" | "low" | "none";

/** Where an impact sits in the review queue — api/services/workflow.py. */
export type ReviewStatus =
  | "detected"
  | "awaiting_review"
  | "in_review"
  | "needs_analysis"
  | "patch_proposed"
  | "awaiting_approval"
  | "resolved"
  | "dismissed"
  | "superseded";

/** How a change was authored (PRD section 8.4). `simulation` is hypothetical. */
export type ChangeSource = "amendment" | "manual" | "simulation";

export type ChangeType =
  | "added"
  | "removed"
  | "threshold"
  | "duration"
  | "scope"
  | "definition"
  | "obligation"
  | "exception"
  | "effective_date"
  | "editorial";

export type RelationshipType = "restates" | "implements" | "references" | "defines";

export type DocType =
  | "policy"
  | "playbook"
  | "sop"
  | "template"
  | "clause_library"
  | "checklist"
  | "opinion"
  | "advisory"
  | "training"
  | "other";

export type ProcessingStatus = "pending" | "processing" | "ready" | "failed";

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

// ------------------------------------------------------------------ domain --

export interface PersonRef {
  id: string;
  display_name: string;
}

/** GET /impacts item, and the `impact` of GET /impacts/{id}. */
export interface Impact {
  id: string;
  regulatory_change_id: string;
  dependency_id: string;
  document_id: string;
  document_chunk_id: string;
  /** Stored, unescalated. */
  impact_level: ImpactLevel;
  /** Derived for display; prefer this everywhere in the UI. */
  severity: Severity;
  confidence: number;
  reason: string;
  conflicting_span: string | null;
  conflicting_start: number | null;
  conflicting_end: number | null;
  review_status: ReviewStatus;
  review_status_label: string;
  /** Present on GET /impacts/{id}; see ImpactListItem.clause_label. */
  clause_label?: string;
  assigned_to: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  due_date: string | null;
  created_at: string;
}

/** The extra columns GET /impacts joins on for its list rows. */
export interface ImpactListItem extends Impact {
  document_name: string;
  doc_type: DocType;
  owner_id: string;
  owner_name: string;
  change_summary: string;
  source: ChangeSource;
  simulation_id: string | null;
  change_type: ChangeType;
  effective_date: string | null;
  section_path: string | null;
  /**
   * Where the passage sits, in the most specific terms available — parsed
   * `section_path`, else `section_title`, else a heading read out of the
   * clause's own text, else its position. Server-decided (api/services/
   * clauses.py) so every screen names the same passage identically. Always
   * populated; never render `section_path` directly.
   */
  clause_label: string;
  /** The sentence around the affected span, for scanning a list. */
  clause_excerpt: string;
  page_number: number | null;
  contributor: Contribution | null;
}

export interface Contribution {
  user: PersonRef | null;
  start: number;
  end: number;
  contributed_at: string;
}

export interface RegulatoryChange {
  id: string;
  lineage_id: string;
  source: ChangeSource;
  simulation_id: string | null;
  change_type: ChangeType;
  old_value: string | null;
  new_value: string | null;
  summary: string;
  source_section: string | null;
  effective_date: string | null;
  analysis_status: "pending" | "analysing" | "complete" | "failed";
  created_at: string;
}

export interface Requirement {
  id: string;
  lineage_id: string;
  requirement_text: string;
  verbatim_text: string | null;
  requirement_type: string;
  subject: string;
  value: string | null;
  value_unit: string | null;
  source_section: string | null;
  source_page: number | null;
  effective_date: string | null;
  version: number;
  is_current: number;
}

export interface Dependency {
  id: string;
  lineage_id: string;
  document_id: string;
  document_chunk_id: string;
  relationship_type: RelationshipType;
  confidence: number;
  rationale: string;
  evidence_span: string | null;
  evidence_start: number | null;
  evidence_end: number | null;
  status: "active" | "dismissed";
}

export interface Recommendation {
  id: string;
  impact_id: string;
  current_text: string;
  suggested_text: string;
  rationale: string;
  requires_human_decision: number;
  decision_note: string | null;
  status: "proposed" | "accepted" | "edited" | "rejected";
  edited_text: string | null;
  generation_method: "model" | "deterministic_fallback";
  source_citations: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface Job {
  id: string;
  job_type: string;
  status: JobStatus;
  progress: number;
  step: string | null;
  error_message: string | null;
  result: Record<string, unknown> | null;
  subject_type: string;
  subject_id: string;
  retryable: number;
  retry_of_job_id: string | null;
  usage: { prompt_tokens: number; completion_tokens: number; estimated_cost_usd: number | null };
}

// ------------------------------------------------------------------- graph --

export type GraphNodeKind = "requirement" | "document" | "section";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  /** `current` / `dependent_unaffected` / `affected_<severity>`. */
  state: string;
  impact_level: Severity | null;
  doc_type?: DocType;
  owner?: string;
  owner_id?: string;
  requirement_text?: string;
  regulation_title?: string;
  parent?: string;
  page?: number | null;
  dependency_count?: number;
  change_source?: ChangeSource | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: RelationshipType;
  confidence: number;
  lineage_id: string;
  document_id: string;
  document_chunk_id: string;
  evidence_start: number | null;
  evidence_end: number | null;
  page_number: number | null;
  impact_level: ImpactLevel | null;
  severity: Severity | null;
  change_source: ChangeSource | null;
  impact_reason: string | null;
  change_summary: string | null;
  affected_start: number | null;
  affected_end: number | null;
  contributor: PersonRef | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  hidden_document_count: number;
  truncated: { nodes_omitted: number; edges_omitted: number };
}

export type SimulationStatus = "draft" | "running" | "complete" | "failed" | "promoted" | "discarded";

export interface SimulationListItem {
  id: string; name: string; note: string | null; status: SimulationStatus;
  edit_count: number; affected_document_count: number; high: number; medium: number; low: number;
  created_at: string; updated_at: string;
}

export interface SimulationEdit {
  id: string; lineage_id: string | null; op: "modify" | "repeal" | "add";
  public_ref: string | null; current_requirement_text: string | null; current_value: string | null;
  proposed_requirement_text: string | null; proposed_value: string | null;
  proposed_value_numeric: number | null; proposed_value_unit: string | null;
}

export interface SimulationImpact {
  id: string; document_id: string; document_chunk_id: string; document_name: string;
  impact_level: ImpactLevel; severity: Severity; confidence: number; reason: string;
  conflicting_start: number | null; conflicting_end: number | null;
  change_summary: string; public_ref: string; clause_label: string;
}

export interface SimulationDetail {
  simulation: SimulationListItem; edits: SimulationEdit[]; changes: RegulatoryChange[];
  impacts: SimulationImpact[];
  totals: { high: number; medium: number; low: number; none: number; documents_examined: number; affected_documents: number; likely_unaffected: number };
}

// ------------------------------------------------------------- workflow --

/**
 * Approved wording, stored as an overlay over the clause it replaces.
 *
 * `char_start` / `char_end` index into the chunk's *stored* content, which
 * approving never changes — the reader composes the two (api/services/
 * patching.py). Never treat `patched_text` as the document's own text.
 */
export interface DocumentPatch {
  id: string;
  document_id: string;
  document_chunk_id: string;
  impact_id: string | null;
  recommendation_id: string | null;
  original_text: string;
  patched_text: string;
  char_start: number;
  char_end: number;
  status: "applied" | "reverted";
  created_by: string;
  created_by_name: string;
  created_at: string;
  reverted_by: string | null;
  reverted_at: string | null;
}

/** One `impact_review_events` row — the narrow, authoritative status record. */
export interface ReviewEvent {
  id: string;
  impact_id: string;
  previous_status: ReviewStatus | null;
  new_status: ReviewStatus;
  changed_by: string;
  changed_by_name: string;
  changed_at: string;
}

/** One `audit_events` row, as returned by GET /impacts/{id}. */
export interface AuditEvent {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  subject_type: string;
  subject_id: string;
  detail: Record<string, unknown> | null;
  created_at: string;
}

/**
 * What this account may do to this impact right now.
 *
 * `allowed_transitions` comes straight from the server's state machine, so
 * the decision bar can only ever offer moves the machine would accept — the
 * UI never has to guess and then apologise with a 422.
 */
export interface ImpactCapabilities {
  change_review_status: boolean;
  generate_recommendation: boolean;
  decide_recommendation: boolean;
  accept_recommendation: boolean;
  approve_patch: boolean;
  revert_patch: boolean;
  allowed_transitions: ReviewStatus[];
}

export interface RecommendationDecision {
  id: string;
  status: Recommendation["status"];
  edited_text: string | null;
  decision_note: string | null;
  decided_by: string;
  decided_by_name: string;
  decided_at: string;
}

export interface RecommendationDetail extends Omit<Recommendation, "source_citations"> {
  source_citations: Array<{ source: "regulation" | "document"; section: string | null; quote: string }>;
  decided_by_name: string | null;
  decision_history: RecommendationDecision[];
}

export interface DocumentChunk {
  id: string;
  document_id: string;
  ordinal: number;
  content: string;
  section_path: string | null;
  section_title: string | null;
  /** See ImpactListItem.clause_label. Present on GET /documents/{id} chunks. */
  clause_label?: string;
  page_number: number | null;
  char_start: number | null;
  char_end: number | null;
  chunk_type: string;
}

/** A sibling finding on the same document — drives "next affected clause". */
export interface SiblingImpact {
  id: string;
  impact_level: ImpactLevel;
  severity: Severity;
  confidence: number;
  review_status: ReviewStatus;
  review_status_label: string;
  conflicting_span: string | null;
  section_path: string | null;
  section_title: string | null;
  clause_label: string;
  ordinal: number;
}

/** GET /impacts/{id} — the whole review screen in one payload. */
export interface ImpactDetail {
  impact: Impact;
  change: RegulatoryChange;
  regulation: { id: string; title: string } | null;
  previous_requirement: Requirement | null;
  new_requirement: Requirement | null;
  dependency: Dependency;
  document: {
    id: string;
    name: string;
    doc_type: DocType;
    status: ProcessingStatus;
    error_message: string | null;
    owner: PersonRef;
    collaborators: Array<PersonRef & { access: string }>;
  };
  chunk: DocumentChunk;
  contributor: Contribution | null;
  recommendation: RecommendationDetail | null;
  patch: DocumentPatch | null;
  review_history: ReviewEvent[];
  audit_trail: AuditEvent[];
  other_open_impacts: SiblingImpact[];
  capabilities: ImpactCapabilities;
}
