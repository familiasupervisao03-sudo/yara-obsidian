// Contratos da API do TITAN (v1). Mantidos em sincronia com
// apps/api/titan_api/schemas.py; o esquema completo está em ../openapi.json
// (gerado por scripts/export_openapi.py e verificado nos testes).

export type UUID = string;
export type ISODateTime = string;

export interface ApiError {
  error: { code: string; message: string; details?: unknown };
}

export interface Health {
  status: "ok";
  service: string;
  version: string;
}

export interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Ready {
  status: "ready" | "not_ready";
  checks: Check[];
}

export interface User {
  id: UUID;
  username: string;
  role: string;
}

export interface SessionInfo {
  user: User;
  expires_at: ISODateTime;
}

export interface Message {
  id: UUID;
  role: "user" | "assistant" | "system";
  content: string;
  model_provider: string | null;
  model_name: string | null;
  created_at: ISODateTime;
}

export interface Conversation {
  id: UUID;
  title: string;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface ConversationList {
  items: Conversation[];
  total: number;
}

export interface ModelStatus {
  available: boolean;
  provider: string;
  detail: string;
}

export interface MessagePostResult {
  user_message: Message;
  reply: Message | null;
  model: ModelStatus;
  duplicate: boolean;
}

export type ServiceState = "online" | "offline" | "disabled" | "unavailable" | "planned";

export interface ServiceStatus {
  name: string;
  state: ServiceState;
  detail: string;
}

export interface SystemStatus {
  version: string;
  phase: string;
  services: ServiceStatus[];
  paid_apis_blocked: boolean;
  external_models_blocked: boolean;
  external_provider_active: boolean;
  paid_budget_brl: number;
  paid_spent_today_brl: number;
  audit_chain_ok: boolean;
}

export interface SettingsView {
  config: Record<string, string | number | boolean>;
  policies: Record<string, string | number | boolean>;
}
