import type {
  ActionInfo,
  ApiError,
  Conversation,
  ConversationDetail,
  ConversationList,
  ExecutionItem,
  ApprovalItem,
  MessagePostResult,
  SessionInfo,
  SettingsView,
  StepInput,
  SystemStatus,
  TaskDetail,
  TaskSummary,
  VoiceStatus,
} from "@titan/api-contracts";

export class HttpError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown,
                          extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  if (method !== "GET") headers["X-Titan-Request"] = "1"; // proteção CSRF exigida pelo backend
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new HttpError(0, "network", "Sem conexão com o servidor do notebook.");
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    // corpo não-JSON
  }
  if (!res.ok) {
    const err = (data as ApiError | null)?.error;
    throw new HttpError(res.status, err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`);
  }
  return data as T;
}

export function newRequestId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export const api = {
  me: () => request<SessionInfo>("GET", "/api/v1/auth/me"),
  login: (username: string, password: string) =>
    request<SessionInfo>("POST", "/api/v1/auth/login", { username, password }),
  logout: () => request<void>("POST", "/api/v1/auth/logout"),
  status: () => request<SystemStatus>("GET", "/api/v1/system/status"),
  settings: () => request<SettingsView>("GET", "/api/v1/settings"),
  conversations: () => request<ConversationList>("GET", "/api/v1/conversations"),
  conversation: (id: string) => request<ConversationDetail>("GET", `/api/v1/conversations/${id}`),
  createConversation: (title: string) =>
    request<Conversation>("POST", "/api/v1/conversations", { title }),
  sendMessage: (id: string, content: string, requestId: string) =>
    request<MessagePostResult>("POST", `/api/v1/conversations/${id}/messages`, {
      content,
      client_request_id: requestId,
    }),
  // tarefas
  catalog: () => request<{ actions: ActionInfo[]; criteria_types: string[] }>("GET", "/api/v1/tasks/catalog"),
  tasks: () => request<{ items: TaskSummary[] }>("GET", "/api/v1/tasks"),
  task: (id: string) => request<TaskDetail>("GET", `/api/v1/tasks/${id}`),
  createTask: (title: string, description: string, steps: StepInput[] | null, key: string) =>
    request<TaskDetail>("POST", "/api/v1/tasks", { title, description, steps }, { "Idempotency-Key": key }),
  setPlan: (id: string, steps: StepInput[], note: string) =>
    request<TaskDetail>("PUT", `/api/v1/tasks/${id}/plan`, { steps, change_note: note }),
  startTask: (id: string) => request<TaskDetail>("POST", `/api/v1/tasks/${id}/start`),
  cancelTask: (id: string, reason: string) =>
    request<TaskDetail>("POST", `/api/v1/tasks/${id}/cancel`, { reason }),
  resumeTask: (id: string, retryUncertain: boolean) =>
    request<TaskDetail>("POST", `/api/v1/tasks/${id}/resume`, { retry_uncertain: retryUncertain }),
  replyTask: (id: string, text: string) => request<TaskDetail>("POST", `/api/v1/tasks/${id}/reply`, { text }),
  executions: (id: string) => request<ExecutionItem[]>("GET", `/api/v1/tasks/${id}/executions`),
  approvals: () => request<ApprovalItem[]>("GET", "/api/v1/approvals"),
  decide: (id: string, decision: "approve" | "reject", scopeHash: string, reason = "") =>
    request<TaskDetail>("POST", `/api/v1/approvals/${id}/decision`, { decision, scope_hash: scopeHash, reason }),
  voiceStatus: () => request<VoiceStatus>("GET", "/api/v1/voice/status"),
};
