import type {
  AcceptedIssue,
  ControlRecord,
  DashboardSummary,
  Envelope,
  EvidenceView,
  Heartbeat,
  Issue,
  IssueDetail,
  IssueSubmission,
  MetricRow,
  RunReplay,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string;

  constructor(status: number, message: string, code: string, traceId: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.traceId = traceId;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = (await response.json()) as Envelope<T>;
  if (!response.ok || (body.code !== 0 && body.code !== "0")) {
    throw new ApiError(response.status, body.message, String(body.code), body.trace_id);
  }
  return body.data as T;
}

export const api = {
  summary: (): Promise<DashboardSummary> => request<DashboardSummary>("/api/v1/dashboard/summary"),

  issues: (status?: string): Promise<Issue[]> => {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<Issue[]>(`/api/v1/issues${query}`);
  },

  issue: (issueId: string): Promise<IssueDetail> => request<IssueDetail>(`/api/v1/issues/${issueId}`),

  submit: (payload: IssueSubmission): Promise<AcceptedIssue> =>
    request<AcceptedIssue>("/api/v1/issues", { method: "POST", body: JSON.stringify(payload) }),

  retry: (issueId: string): Promise<{ issue_id: string; queued: boolean; status: string }> =>
    request(`/api/v1/issues/${issueId}/retry`, { method: "POST" }),

  handoff: (issueId: string, actor: string, reason: string): Promise<{ handoff: boolean; status: string }> =>
    request(`/api/v1/issues/${issueId}/handoff`, {
      method: "POST",
      body: JSON.stringify({ actor, reason }),
    }),

  disposition: (issueId: string): Promise<EvidenceView> =>
    request<EvidenceView>(`/api/v1/issues/${issueId}/disposition`),

  replay: (runId: string): Promise<RunReplay> => request<RunReplay>(`/api/v1/runs/${runId}/replay`),

  metrics: (): Promise<MetricRow[]> => request<MetricRow[]>("/api/v1/metrics"),

  controlEvents: (): Promise<ControlRecord[]> => request<ControlRecord[]>("/api/v1/control/events"),

  pause: (actor: string, reason: string): Promise<{ paused: boolean; reason: string }> =>
    request("/api/v1/control/pause", { method: "POST", body: JSON.stringify({ actor, reason }) }),

  resume: (): Promise<{ paused: boolean }> => request("/api/v1/control/resume", { method: "POST" }),

  resetCircuit: (defectClass: string, actor: string, reason: string): Promise<{ state: string }> =>
    request(`/api/v1/circuits/${defectClass}/reset`, {
      method: "POST",
      body: JSON.stringify({ actor, reason }),
    }),

  heartbeat: (): Promise<Heartbeat> => request<Heartbeat>("/api/v1/heartbeat", { method: "POST" }),

  streamUrl: (since: number, iterations: number): string =>
    `/api/v1/events/stream?since=${since}&iterations=${iterations}&interval=5`,
};