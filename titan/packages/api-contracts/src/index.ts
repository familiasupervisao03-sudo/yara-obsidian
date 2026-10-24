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
  status?: "complete" | "interrupted" | "error";
  interrupted_at_char?: number | null;
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

// ---------- Fase 2: tarefas e aprovações ----------

export type TaskStatus =
  | "RECEIVED" | "PLANNING" | "PENDING_APPROVAL" | "READY" | "RUNNING" | "VERIFYING"
  | "WAITING_FOR_USER" | "CANCEL_REQUESTED" | "CANCELLED" | "INTERRUPTED" | "COMPLETED" | "FAILED";

export interface Criterion {
  type: "output_nonempty" | "contains" | "not_contains" | "equals" | "max_length";
  value?: string | number;
}

export interface StepInput {
  title: string;
  description?: string;
  action_type: string;
  parameters: Record<string, string>;
  success_criteria: Criterion[];
  requires_approval?: boolean;
  depends_on?: number[];
}

export interface TaskSummary {
  id: UUID;
  title: string;
  description: string;
  status: TaskStatus;
  status_reason: string | null;
  plan_version: number;
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface TaskStep {
  id: UUID;
  position: number;
  title: string;
  description: string;
  action_type: string;
  action_label: string;
  parameters: Record<string, unknown>;
  requires_approval: boolean;
  depends_on: number[];
  success_criteria: Criterion[];
  status: string;
  last_output: string | null;
  last_error: string | null;
}

export interface ApprovalItem {
  id: UUID;
  task_id: UUID;
  task_title: string;
  step_position: number | null;
  step_title: string | null;
  plan_version: number;
  action_type: string;
  action_label: string;
  parameters: Record<string, unknown>;
  risk: string;
  scope_hash: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "INVALIDATED" | "EXPIRED";
  expires_at: ISODateTime | null;
  decided_at: ISODateTime | null;
  reason: string | null;
  created_at: ISODateTime;
}

export interface TaskDetail {
  task: TaskSummary;
  steps: TaskStep[];
  approvals: ApprovalItem[];
  plans: { version: number; created_by: string; change_note: string; created_at: ISODateTime }[];
  verification: { criterion: string; passed: boolean; details: string; created_at: ISODateTime }[];
}

export interface ActionInfo {
  name: string;
  label: string;
  sensitive: boolean;
  risk: string;
  required_params: string[];
  available: boolean;
  unavailable_reason: string;
}

export interface ExecutionItem {
  id: UUID;
  step_id: UUID | null;
  attempt: number;
  command: string;
  status: string;
  output: string;
  error: string;
  started_at: ISODateTime;
  finished_at: ISODateTime | null;
}

export interface TaskEvent {
  event_type: string;
  actor_type: string;
  created_at: ISODateTime;
  data: Record<string, unknown>;
  task_status: TaskStatus;
}

// ---------- voz ----------

export interface VoiceEngine {
  name: string;
  kind: "stt" | "tts";
  available: boolean;
  local: boolean;
  detail: string;
}

export interface VoiceStatus {
  engines: VoiceEngine[];
  sample_rate: number;
  notes: string[];
}

// Preferências explícitas do usuário (GET/PUT/DELETE /api/v1/preferences)
export interface Correction {
  heard: string;
  meant: string;
}

export interface Preferences {
  response_length: "curta" | "normal" | "detalhada";
  formality: "informal" | "neutra" | "formal";
  examples: "auto" | "sim" | "nao";
  voice_rate: number; // % da velocidade normal da voz (-30 a 30)
  corrections: Correction[];
}
