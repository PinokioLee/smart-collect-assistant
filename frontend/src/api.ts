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
