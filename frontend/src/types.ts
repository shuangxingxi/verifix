export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type DefectClass = "C01" | "C02" | "C03" | "C05";
export type DispositionLevel = "L0" | "L1" | "L2" | "L3";
export type VerdictConclusion = "REACHABLE" | "UNREACHABLE" | "SUSPECTED";

export type IssueStatus =
  | "RECEIVED"
  | "TRIAGING"
  | "REACHABLE"
  | "SUSPECTED"
  | "ARCHIVED"
  | "REPRODUCING"
  | "PROVEN"
  | "REPRO_FAILED"
  | "PATCHING"
  | "AUDITING"
  | "GATING"
  | "ROLLING_BACK"
  | "DISPOSED_L0"
  | "DISPOSED_L1"
  | "DISPOSED_L2"
  | "DISPOSED_L3";

export interface Envelope<T> {
  code: number | string;
  message: string;
  data: T | null;
  trace_id: string;
}

export interface Issue {
  issue_id: string;
  repo: string;
  code_version: string;
  defect_class: DefectClass | null;
  severity: Severity;
  status: IssueStatus;
  source_count: number;
  fingerprint: string;
  in_scope: boolean;
  occurred_at: string;
  updated_at: string;
}

export interface Verdict {
  verdict_id: string;
  issue_id: string;
  conclusion: VerdictConclusion;
  confidence: number;
  taint_path: string[];
  basis: string;
  decided_by: string;
  decided_at: string;
  is_effective: boolean;
}

export interface Proof {
  proof_id: string;
  issue_id: string;
  test_path: string;
  pre_patch_result: string;
  post_patch_result: string;
  fingerprint: string;
  generated_marker: string;
  created_at: string;
}

export interface Patch {
  patch_id: string;
  issue_id: string;
  proof_id: string;
  branch: string;
  diff_ref: string;
  lines_changed: number;
  files_changed: number;
  fix_paradigm: string;
  patch_strength: number;
  quotas_ok: boolean;
  created_at: string;
}

export interface Disposition {
  disposition_id: string;
  issue_id: string;
  level: DispositionLevel;
  action: string;
  evidence_ref: string;
  reason_code: string;
  decided_at: string;
  gate_outcome: string | null;
}

export interface AlertRecord {
  alert_ref: string;
  source_kind: string;
  rule_id: string;
  location: { file: string; line: number | null; component: string | null; component_version: string | null };
  raw_severity: Severity;
  snippet: string;
}

export interface IssueDetail {
  issue: Issue;
  verdict: Verdict | null;
  proof: Proof | null;
  patch: Patch | null;
  disposition: Disposition | null;
  alerts: AlertRecord[];
}

export interface DashboardSummary {
  in_progress: number;
  archived: number;
  level_distribution: Record<string, number>;
  circuit_open_classes: string[];
  circuit_states: Record<string, string>;
  paused: boolean;
  pause_reason: string;
  self_run_hours: number;
  interruptions: number;
  failure_reasons: [string, number][];
  metrics: Array<{ metric_id: string; value: number | null; computable: boolean; source_ref: string; computed_at: string }>;
  generated_at: string;
}

export interface ReplayStep {
  kind: string;
  status: string;
  executed: boolean;
  started_at: string | null;
  ended_at: string | null;
  evidence_ref: string | null;
}

export interface ReplayEvent {
  seq: number;
  event_type: string;
  occurred_at: string;
  actor: string;
  step: string | null;
  payload_ref: string | null;
}

export interface RunReplay {
  run_id: string;
  issue_id: string;
  terminal_state: string | null;
  started_at: string;
  ended_at: string | null;
  steps: ReplayStep[];
  missing_steps: string[];
  events: ReplayEvent[];
  chain_valid: boolean;
}

export interface MetricRow {
  metric_id: string;
  stage_tier: string;
  window: string;
  value: number | null;
  computable: boolean;
  source_ref: string;
  definition_version: string;
}

export interface ControlRecord {
  action: string;
  actor: string;
  reason: string;
  scope: string;
  occurred_at: string;
}

export interface EvidenceView {
  disposition_id: string;
  issue_id: string;
  level: string;
  action: string;
  reason_code: string;
  evidence_ref: string;
  evidence_ok: boolean;
  evidence_detail: string;
  conclusion_trusted: boolean;
}

export interface AcceptedIssue {
  issue_id: string;
  run_id: string;
  status: string;
  idempotent: boolean;
  in_scope: boolean;
}

export interface Heartbeat {
  healthy: boolean;
  self_run_hours: number;
  interruptions: number;
}

export interface IssueSubmission {
  repo: string;
  code_version: string;
  rule_id: string;
  severity: Severity;
  file: string;
  line: number | null;
  defect_class: DefectClass | null;
  snippet: string;
}