const TOKEN: string =
  (import.meta as any).env?.VITE_API_TOKEN ?? "dev-token-2026";

export interface SessionSummary {
  id: number;
  topic: string;
  report_type: string;
  status: string;
  created_at: string;
}

export interface Verdict {
  passed: boolean;
  issues: string[];
}

export interface SessionDetail extends SessionSummary {
  finished_at?: string;
  report?: {
    verdict: Verdict;
    revision_rounds: number;
    report_path: string;
    created_at: string;
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Token": TOKEN,
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`请求失败 HTTP ${res.status}`);
  }
  return res.json();
}

export function createSession(topic: string, reportType: string) {
  return request<{ session_id: number; task_id: string }>("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ topic, report_type: reportType }),
  });
}

export function getSession(id: number) {
  return request<SessionDetail>(`/api/v1/sessions/${id}`);
}

export function getReportMd(id: number) {
  return request<{ report_md: string }>(`/api/v1/sessions/${id}/report`);
}

export function listSessions(limit = 20) {
  return request<{ sessions: SessionSummary[] }>(
    `/api/v1/sessions?limit=${limit}`
  );
}

export interface StreamHandlers {
  onEvent: (type: string, data: any) => void;
  onEnd: () => void;
}

export function streamEvents(sessionId: number, handlers: StreamHandlers) {
  // EventSource 无法自定义 Header → token 走 query（后端同时支持 header/query）
  const es = new EventSource(
    `/api/v1/sessions/${sessionId}/events?token=${encodeURIComponent(TOKEN)}`
  );
  const parse = (e: MessageEvent): any => {
    try {
      return JSON.parse(e.data);
    } catch {
      return {};
    }
  };
  es.addEventListener("phase", (e) =>
    handlers.onEvent("phase", parse(e as MessageEvent))
  );
  es.addEventListener("done", (e) => {
    handlers.onEvent("done", parse(e as MessageEvent));
    es.close();
    handlers.onEnd();
  });
  es.addEventListener("error", (e) => {
    handlers.onEvent("error", parse(e as MessageEvent));
    es.close();
    handlers.onEnd();
  });
  return es;
}
