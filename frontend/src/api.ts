import axios from "axios";
import type { CollectResponse } from "./types";

const client = axios.create({ baseURL: "/api" });

export interface Health {
  status: string;
  azure_ready: boolean;
  use_rag: boolean;
  use_langfuse: boolean;
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
