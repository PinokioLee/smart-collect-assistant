import axios from "axios";
import type { CollectResponse } from "./types";

const client = axios.create({ baseURL: "/api" });

export interface Health {
  status: string;
  azure_ready: boolean;
  use_rag: boolean;
  use_langfuse: boolean;
  email_send_mode: string;
  gmail_ready: boolean;
}

export async function getHealth(): Promise<Health> {
  const { data } = await client.get<Health>("/health");
  return data;
}

export async function getSampleEmail(): Promise<{ subject: string; body: string }> {
  const { data } = await client.get("/sample-email");
  return data;
}

export async function genSamples(): Promise<{ email: string; excels: string[] }> {
  const { data } = await client.post("/gen-samples");
  return data;
}

export interface HardSamplesResponse {
  email: string;
  excels: string[];
  expected: {
    total_files: number;
    total_rows: number;
    error_rows: number;
    valid_rows: number;
    error_types: string[];
    self_correction_applied: number;
    self_correction_fixable: number;
  };
}

export async function genHardSamples(): Promise<HardSamplesResponse> {
  const { data } = await client.post<HardSamplesResponse>("/gen-hard-samples");
  return data;
}

export interface ProjectSamplesResponse {
  common_columns: string[];
  excels: string[];
  reference: string;
  targets: string[];
}

export async function genProjectSamples(): Promise<ProjectSamplesResponse> {
  const { data } = await client.post<ProjectSamplesResponse>("/gen-project-samples");
  return data;
}

export interface CollectInput {
  subject: string;
  body: string;
  useGraph: boolean;
  useLlm: boolean;
  files: File[];
}

export async function collect(input: CollectInput): Promise<CollectResponse> {
  const form = new FormData();
  form.append("subject", input.subject);
  form.append("body", input.body);
  form.append("use_graph", String(input.useGraph));
  form.append("use_llm", String(input.useLlm));
  input.files.forEach((f) => form.append("files", f));
  const { data } = await client.post<CollectResponse>("/collect", form);
  return data;
}

export function downloadUrl(path: string): string {
  return path; // 서버가 절대경로(/api/...) 반환
}

export interface GuideResponse {
  extracted: {
    request_title: string | null;
    purpose: string | null;
    deadline: string | null;
    required_fields: string[];
    cautions: string[];
    missing_info: string[];
  };
  guide: {
    guide_title: string;
    guide_body: string;
    field_instructions: { field: string; how: string }[];
  };
  mail_draft: {
    mail_subject: string;
    mail_body: string;
  };
  llm_used: boolean;
  style_used: boolean;
  style_sources: string[];
}

export async function createGuide(subject: string, body: string): Promise<GuideResponse> {
  const form = new FormData();
  form.append("subject", subject);
  form.append("body", body);
  const { data } = await client.post<GuideResponse>("/guide", form);
  return data;
}

export interface StyleMailsResponse {
  count: number;
  files: string[];
}

export async function getStyleMails(): Promise<StyleMailsResponse> {
  const { data } = await client.get<StyleMailsResponse>("/style-mails");
  return data;
}

export async function saveStyleMail(subject: string, body: string): Promise<{ saved: string; count: number }> {
  const { data } = await client.post("/save-style-mail", { subject, body });
  return data;
}

export async function uploadStyleMails(files: File[]): Promise<{ saved: string[]; count: number }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const { data } = await client.post("/upload-style-mails", form);
  return data;
}

export interface SendEmailInput {
  to: string[];
  subject: string;
  body: string;
  cc?: string[];
  attachment_paths?: string[];
}

export interface SendEmailResponse {
  status: string;
  mode: string;
  recipients: string[];
  subject: string;
  message_id: string | null;
  detail: string | null;
}

export async function sendEmail(input: SendEmailInput): Promise<SendEmailResponse> {
  const { data } = await client.post<SendEmailResponse>("/send-email", input);
  return data;
}

export interface SendRequestMailResponse extends SendEmailResponse {
  attachments: string[];
}

export async function sendRequestMail(input: {
  to: string;
  subject: string;
  body: string;
  files: File[];
}): Promise<SendRequestMailResponse> {
  const form = new FormData();
  form.append("to", input.to);
  form.append("subject", input.subject);
  form.append("body", input.body);
  input.files.forEach((f) => form.append("files", f));
  const { data } = await client.post<SendRequestMailResponse>("/send-request-mail", form);
  return data;
}

export interface TrackResponse {
  submitted_list: Array<{ name: string; dept: string; email: string; submitted_at?: string }>;
  missing_list: Array<{ name: string; dept: string; email: string }>;
  late_list: Array<{ name: string; dept: string; email: string; submitted_at?: string }>;
  submission_rate: number;
  summary: string;
  reminder?: {
    reminder_mail_subject: string;
    reminder_mail_body: string;
  };
}

export async function trackSubmissions(submitted: string[], deadline: string): Promise<TrackResponse> {
  const { data } = await client.post<TrackResponse>("/track", { submitted, deadline });
  return data;
}

export interface UpdateFieldsResponse {
  updated_files: string[];
  update_count: number;
  details: Array<{ file: string; updated_cells: number; output: string }>;
  error_list: Array<{ file: string; reason: string }>;
  downloads: string[];
  request_id: string;
}

export async function updateFields(input: {
  targetField: string;
  newValue: string;
  oldValue?: string;
  files: File[];
}): Promise<UpdateFieldsResponse> {
  const form = new FormData();
  form.append("target_field", input.targetField);
  form.append("new_value", input.newValue);
  form.append("old_value", input.oldValue ?? "");
  input.files.forEach((f) => form.append("files", f));
  const { data } = await client.post<UpdateFieldsResponse>("/update-fields", form);
  return data;
}

// ---------- 수신함 자동 분류 (Phase A/B) ----------

export interface Grounding {
  checks: { item: string; grounded: boolean; source: string }[];
  flags: string[];
  score: number;
}

export interface InboxItem {
  message_id: string;
  sender: string;
  subject: string;
  received_at: string;
  classification: string;
  confidence: number;
  tier: string;
  status: string;
  draft_subject?: string | null;
  draft_body?: string | null;
  recipients: { name: string; dept: string; email: string }[];
  reasons: string[];
  source: string;
  grounding: Grounding;
  sources: string[];
  sent: boolean;
}

export interface IngestResult {
  fetched: number;
  processed_new: number;
  skipped: number;
  by_status: Record<string, number>;
  queue: InboxItem[];
  read_mode: string;
}

export async function inboxIngest(useLlm = true): Promise<IngestResult> {
  const form = new FormData();
  form.append("use_llm", String(useLlm));
  const { data } = await client.post<IngestResult>("/inbox/ingest", form);
  return data;
}

export async function inboxQueue(
  status?: string
): Promise<{ queue: InboxItem[]; counts: Record<string, number>; read_mode: string }> {
  const { data } = await client.get("/inbox/queue", {
    params: status ? { status } : {},
  });
  return data;
}

export async function inboxSend(
  messageId: string
): Promise<{ message_id: string; send_result: SendEmailResponse }> {
  const { data } = await client.post(`/inbox/${encodeURIComponent(messageId)}/send`);
  return data;
}

// ---------- 자동 수집 스케줄 (Phase C) ----------

export interface ScheduleConfig {
  enabled: boolean;
  mode: "interval" | "times" | "weekly";
  interval_hours: number;
  times: string[];
  weekday: number;
  weekly_time: string;
}

export interface ScheduleStatus {
  config: ScheduleConfig;
  running: boolean;
  next_runs: string[];
  last_run: string | null;
  last_summary: { fetched: number; processed_new: number; by_status: Record<string, number> } | null;
  last_error: string | null;
}

export async function getSchedule(): Promise<ScheduleStatus> {
  const { data } = await client.get<ScheduleStatus>("/schedule");
  return data;
}

export async function setSchedule(cfg: Partial<ScheduleConfig>): Promise<ScheduleStatus> {
  const { data } = await client.post<ScheduleStatus>("/schedule", cfg);
  return data;
}

export async function scheduleRunNow(): Promise<{ result: any; status: ScheduleStatus }> {
  const { data } = await client.post("/schedule/run-now");
  return data;
}

export interface SyncCommonFieldsResponse extends UpdateFieldsResponse {
  common_columns: string[];
  key_column: string;
  reference_file: string;
}

export async function syncCommonFields(input: {
  referenceFile: File;
  targetFiles: File[];
}): Promise<SyncCommonFieldsResponse> {
  const form = new FormData();
  form.append("reference_file", input.referenceFile);
  input.targetFiles.forEach((f) => form.append("target_files", f));
  const { data } = await client.post<SyncCommonFieldsResponse>("/sync-common-fields", form);
  return data;
}
