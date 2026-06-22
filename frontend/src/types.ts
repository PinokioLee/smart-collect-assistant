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

export interface CollectResponse {
  request_id: string;
  current_stage: string;
  extracted_requirements: ExtractedRequirements | null;
  validation_rules: ValidationRule | null;
  validation_result: ValidationResult | null;
  merged_file: string | null;
  error_report: string | null;
  result_summary: string | null;
  agent_handoff_history: string[];
  downloads: { merged: string | null; error: string | null };
}
