export interface ExtractedRequirements {
  request_title: string | null;
  purpose: string | null;
  deadline: string | null;
  required_fields: string[];
  cautions: string[];
  missing_info: string[];
}

export interface ValidationRule {
  required_columns: string[];
  date_columns: string[];
  code_rules: Record<string, string[]>;
  duplicate_keys: string[];
}

export interface ErrorDetail {
  file: string;
  row: number;
  column: string | null;
  error_type: string;
  value: string | null;
  detail: string | null;
}

export interface ValidationResult {
  total_files: number;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  error_types: string[];
  error_details: ErrorDetail[];
}

export interface Correction {
  file: string;
  row: number;
  column: string;
  error_type: string;
  before: string;
  after: string;
  method: string;
  source: string; // "llm" | "rule"
  rationale: string | null;
  verified: boolean;
}

export interface SelfCorrectionResult {
  fixable_errors: number;
  applied_corrections: number;
  errors_before: number;
  errors_after: number;
  accepted: boolean;
  auto_fix_rate: number;
  corrections: Correction[];
}

export interface SupervisorPlan {
  strategy?: string;
  required_focus?: string[];
  drift_columns?: string[];
  risks?: string[];
  rationale?: string;
  source?: string;
}

export interface ReasoningStep {
  seq: number;
  agent: string;
  node: string;
  phase: string;
  decision: string;
  actor: string; // "llm" | "rule"
  detail: Record<string, unknown>;
}

export interface CollectResponse {
  request_id: string;
  current_stage: string;
  extracted_requirements: ExtractedRequirements | null;
  validation_rules: ValidationRule | null;
  validation_result: ValidationResult | null;
  self_correction: SelfCorrectionResult | null;
  supervisor_plan: SupervisorPlan | null;
  merged_file: string | null;
  error_report: string | null;
  result_summary: string | null;
  agent_handoff_history: string[];
  reasoning_log: string[];
  reasoning_steps: ReasoningStep[];
  downloads: {
    merged: string | null;
    error: string | null;
    trace_md: string | null;
    trace_json: string | null;
  };
}
