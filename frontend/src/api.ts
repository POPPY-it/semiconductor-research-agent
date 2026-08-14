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

export function login() {
  return request<{ ok: boolean }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ token: TOKEN }),
  });
}

export function createSession(topic: string, reportType: string) {
  return request<{ session_id: number; task_id: string }>("/api/v1/sessions", {
    method: "POST",
    body: JSON.stringify({ topic, report_type: reportType }),
  });
}

export function retrySession(id: number) {
  return request<{ session_id: number; task_id: string }>(
    `/api/v1/sessions/${id}/retry`,
    { method: "POST", body: "{}" }
  );
}

export interface QaResult {
  question: string;
  answer: string;
  sources: { title: string; url: string }[];
  conversation_id?: number;
}

export function askQuestion(question: string, conversationId?: number) {
  return request<QaResult>("/api/v1/qa", {
    method: "POST",
    body: JSON.stringify({ question, conversation_id: conversationId ?? null }),
  });
}

export interface ConversationSummary {
  id: number;
  title: string;
  created_at: string;
  msg_count: number;
}

export interface QaMessage {
  role: string;
  content: string;
  sources: { title: string; url: string }[];
}

export function listConversations() {
  return request<{ conversations: ConversationSummary[] }>(
    "/api/v1/qa/conversations"
  );
}

export function getConversation(id: number) {
  return request<{ messages: QaMessage[] }>(`/api/v1/qa/conversations/${id}`);
}

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/v1/documents", {
    method: "POST",
    headers: { "X-API-Token": TOKEN },
    body: form,
  });
  if (!res.ok) throw new Error(`上传失败 HTTP ${res.status}`);
  return res.json();
}

export function listDocuments() {
  return request<{ documents: { title: string; chars: number }[] }>(
    "/api/v1/documents"
  );
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
  // 认证走 HttpOnly Cookie（登录接口签发），EventSource 同源自动携带，token 不进 URL
  const es = new EventSource(`/api/v1/sessions/${sessionId}/events`);
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
