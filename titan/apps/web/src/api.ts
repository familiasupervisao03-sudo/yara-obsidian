import type {
  ApiError,
  ConversationDetail,
  ConversationList,
  Conversation,
  MessagePostResult,
  SessionInfo,
  SettingsView,
  SystemStatus,
} from "@titan/api-contracts";

export class HttpError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-Titan-Request"] = "1"; // proteção CSRF exigida pelo backend
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
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
  // A chave de idempotência evita mensagens duplicadas em reenvios.
  sendMessage: (id: string, content: string, requestId: string) =>
    request<MessagePostResult>("POST", `/api/v1/conversations/${id}/messages`, {
      content,
      client_request_id: requestId,
    }),
};
