// Shared types for the API

export interface User {
  id: string;
  github_id: string;
  github_username: string;
  github_avatar_url: string | null;
  github_connected?: boolean;
  username?: string;
  avatar_url?: string;
  created_at: string;
}

export interface GitHubRepoItem {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  html_url: string;
  clone_url: string;
  description: string | null;
  private: boolean;
  default_branch: string;
  language: string | null;
  updated_at: string | null;
}

export interface GitHubReposResponse {
  connected: boolean;
  repos: GitHubRepoItem[];
  total: number;
  username: string | null;
}

export type SourceType = "upload" | "github";

export type PipelineStatus =
  | "PENDING"
  | "CLONING"
  | "PARSING"
  | "EMBEDDING"
  | "ANALYZING"
  | "DETECTING_ERRORS"
  | "AUTO_FIXING"
  | "DONE"
  | "FAILED";

export interface PipelineStatusResponse {
  repo_id: string;
  pipeline_status: PipelineStatus;
  message: string;
  error: string | null;
  meta_summary: {
    total_files: number | null;
    total_symbols: number | null;
    language_dist: Record<string, number> | null;
    total_issues: number | null;
  } | null;
}

export interface RepoSummary {
  repo_id: string;
  name: string;
  source_type: SourceType;
  created_at?: string;
  file_count: number;
  pipeline_status?: PipelineStatus;
  detected_ci?: boolean;
  detected_ci_files?: string[];
  needs_ci_setup?: boolean;
  last_activity_at?: string;
  last_activity_summary?: string;
  last_commit_sha?: string;
  last_commit_message?: string;
  last_commit_branch?: string;
  last_commit_time?: string;
}

export interface ConversationItem {
  id: string;
  repo_id: string;
  title: string;
  last_message_preview?: string | null;
  model_provider?: string | null;
  model_name?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface FixTaskLogEntry {
  timestamp: string;
  step: string;
  detail?: string;
  status: "pending" | "running" | "done" | "info" | "error";
}

export interface FixTask {
  taskId: string;
  repoId: string;
  repoName: string;
  errorReport: ErrorReport;
  stage: "COLLECTING" | "INSPECTING" | "GENERATING" | "VALIDATING" | "READY" | "APPLIED" | "FIX_APPLIED" | "REJECTED" | "FAILED";
  log: FixTaskLogEntry[];
  explanation?: string;
  diff?: string;
  linesAdded?: number;
  linesDeleted?: number;
  testCommand?: string;
  testOutput?: string;
  passed?: boolean;
  error?: string;
  failureType?: string;
  patch_status?: string;
  validation_status?: "NOT_RUN" | "PASSED" | "FAILED";
  validation_skipped?: boolean;
  validation_notice?: string;
  changed_files?: string[];
  createdAt: number;
}

export interface ChatActionPill {
  id: string;
  label: string;
  action: () => void | Promise<void>;
  status?: "idle" | "running" | "done" | "error";
}

export interface FileNode {
  name: string;
  type: "file" | "directory";
  path?: string;
  language?: string | null;
  size?: number;
  children?: FileNode[];
}

export interface RepoFilesResponse {
  repo_id: string;
  name: string;
  source_type: SourceType;
  tree: FileNode;
  total_files: number;
}

export interface Citation {
  index: number;
  file_path: string;
  symbol_type: string;
  name: string;
  start_line: number;
  end_line: number;
  language: string | null;
  score: number;
  source_code: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  errorReports?: ErrorReport[];
  imageUrl?: string;
  images?: string[];
  isStreaming?: boolean;
  isStopped?: boolean;
  queuedNext?: boolean;
  fixTask?: FixTask;
  actionPills?: ChatActionPill[];
  analysisStatus?: string | null;
  fallbackNotice?: string | null;
}

export type EmbedStatus = "not_started" | "running" | "done" | "error" | "already_running";

export type DocExportStatus = "not_started" | "running" | "done" | "error" | "already_running";

export interface DocFileEntry {
  path: string;
  size: number;
}

export type DocSectionStatus = "fully_generated" | "fallback" | "failed" | "COMPLETE" | "FAILED" | "PENDING";

export interface SectionValidationInfo {
  section_number: number;
  title: string;
  filename: string;
  status: DocSectionStatus;
  has_diagram: boolean;
  warnings?: string[];
  is_complete?: boolean;
}

export interface DocValidationSummary {
  total_sections: number;
  fully_generated: number;
  fallback: number;
  failed: number;
  is_complete?: boolean;
  errors?: string[];
  sections?: Record<number, SectionValidationInfo>;
}

export interface DocSectionItem {
  section_number?: number;
  filename: string;
  title: string;
  content: string;
  status?: DocSectionStatus;
  is_complete?: boolean;
  has_diagram?: boolean;
  warnings?: string[];
}

export interface MasterDocsResponse {
  repo_id: string;
  is_complete?: boolean;
  master_readme: string;
  validation_summary?: DocValidationSummary;
  sections: DocSectionItem[];
}

export interface CommitDocsResponse {
  repo_id: string;
  status: "pr_opened" | "applied_local" | "error";
  message: string;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
  pr_number?: number | null;
  pr_status?: string | null;
  auto_merge_enabled?: boolean;
}

export interface DocExportResult {
  repo_id: string;
  status: DocExportStatus;
  result?: {
    total_symbols: number;
    documented_symbols: number;
    doc_files: DocFileEntry[];
    errors: string[];
  };
  error?: string;
}

// ── Codefix types ─────────────────────────────────────────────────────────────

export interface SymbolInfo {
  id: number;
  symbol_type: string;
  name: string;
  file_path: string;
  language: string | null;
  source_code: string;
}

export interface FixResult {
  symbol_id: number;
  file_path: string;
  language: string;
  diff: string;
  model_used: string;
  model_display_name?: string;
  provider?: string;
  fallback_used?: boolean;
  fix_attribution?: string;
  attempts?: any[];
}

export interface ValidationResult {
  repo_id: string;
  file_path: string;
  passed: boolean;
  test_command: string;
  exit_code: number;
  output: string;
  error: string;
  failure_type?: string;
}

export interface ExplainResult {
  symbol_id: number;
  explanation: string;
}

// ── Voice types ───────────────────────────────────────────────────────────────

export type VoiceIntent = "ask_question" | "explain_symbol" | "generate_fix" | "generate_docs";

export interface TranscribeResponse {
  text: string;
  intent: VoiceIntent;
  target: string;
  confidence: number;
}

// ── GitOps types ──────────────────────────────────────────────────────────────

export interface ApplyFixRequest {
  diff: string;
  file_path: string;
  branch_name?: string;
  commit_message?: string;
  pr_title?: string;
  pr_body?: string;
  base_branch?: string;
}

export interface ApplyFixResponse {
  repo_id: string;
  branch_name: string;
  commit_sha: string;
  pr_url: string;
  pr_number: number | null;
  provider: "github" | "unknown";
}

// ── Error Reports (Issues tab) ────────────────────────────────────────────────

export type FixStatus =
  | "PENDING"
  | "GENERATING"
  | "PATCH_GENERATED"
  | "READY"
  | "READY_TO_APPLY"
  | "SANDBOX_FAILED"
  | "ENVIRONMENT_FAILED"
  | "APPLIED"
  | "APPLIED_LOCAL"
  | "FIX_APPLIED"
  | "OPEN"
  | "REJECTED"
  | "FAILED"
  | "PATCH_GENERATION_FAILED"
  | "PATCH_APPLICATION_FAILED";

export type PRStatus = "NONE" | "OPEN" | "OPEN_AUTO_MERGE_ENABLED" | "OPEN_MANUAL_MERGE_REQUIRED" | "OPEN_NO_CI" | "MERGED" | "FAILED_PIPELINE";

export interface ErrorReport {
  id: string;
  repo_id: string;
  symbol_id: number | null;
  rule_id: string;
  category?: "ERROR" | "WARNING" | "RECOMMENDATION";
  severity: "error" | "warning" | "info";
  message: string;
  file_path: string;
  symbol_name: string | null;
  symbol_type: string | null;
  language: string | null;
  line: number | null;
  explanation: string | null;
  suggested_fix: string | null;
  fix_status: FixStatus;
  fix_model: string | null;
  fix_provider?: string | null;
  fix_attribution?: string | null;
  fix_attempts?: any[] | null;
  provider_used?: string | null;
  model_used?: string | null;
  fallback_used?: boolean;
  fix_error: string | null;
  is_environment_failure?: boolean;
  failure_type?: string;
  missing_dependencies?: string[];
  working_directory?: string;
  exit_code?: number;
  branch_name?: string | null;
  pr_url?: string | null;
  pr_id?: number | null;
  pr_status?: PRStatus;
  auto_fix_attempted?: number;
  created_at: string;
  patch_status?: string;
  validation_status?: "NOT_RUN" | "PASSED" | "FAILED";
  validation_skipped?: boolean;
  validation_notice?: string;
  changed_files?: string[];
}

export interface ErrorReportsResponse {
  repo_id: string;
  total: number;
  errors: ErrorReport[];
}

export interface GenerateErrorFixResponse {
  error_id: string;
  fix_status: FixStatus;
  passed: boolean;
  is_environment_failure?: boolean;
  explanation?: string | null;
  suggested_fix?: string | null;
  test_command: string;
  working_directory?: string;
  python_executable?: string;
  exit_code?: number;
  output: string;
  stdout?: string;
  stderr?: string;
  error: string | null;
  missing_dependencies?: string[];
  failure_type?: string;
  provider_used?: string | null;
  model_used?: string | null;
  fallback_used?: boolean;
  fix_attribution?: string | null;
  attempts?: any[];
  patch_status?: string;
  validation_status?: "NOT_RUN" | "PASSED" | "FAILED";
  validation_skipped?: boolean;
  validation_notice?: string;
  changed_files?: string[];
}

export interface ApplyErrorFixResponse {
  error_id: string;
  passed: boolean;
  fix_status: FixStatus;
  pr_status?: PRStatus;
  branch_name?: string | null;
  pr_url?: string | null;
  pr_id?: number | null;
  test_command: string;
  output: string;
  error: string;
  patch_status?: string;
  validation_status?: "NOT_RUN" | "PASSED" | "FAILED";
  validation_skipped?: boolean;
  validation_notice?: string;
  changed_files?: string[];
}

// ── Automation Log Types ─────────────────────────────────────────────────────

export type AutomationStage =
  | "DETECTED"
  | "FIX_GENERATED"
  | "SANDBOX_PASSED"
  | "SANDBOX_FAILED"
  | "ENVIRONMENT_FAILED"
  | "BRANCH_PUSHED"
  | "PR_OPENED"
  | "PIPELINE_PASSED"
  | "PIPELINE_FAILED"
  | "MERGED"
  | "SKIPPED";

export interface AutomationLogEntry {
  id: string;
  error_id: string | null;
  stage: AutomationStage;
  outcome: "SUCCESS" | "FAILED" | "INFO";
  message: string;
  details: string | null;
  created_at: string | null;
}

export interface AutomationLogSummary {
  total_issues: number;
  auto_fix_attempted: number;
  sandbox_passed: number;
  sandbox_failed: number;
  prs_opened: number;
  merged: number;
  pipeline_failed: number;
}

export interface AutomationLogResponse {
  repo_id: string;
  repo_name: string;
  summary: AutomationLogSummary;
  logs: AutomationLogEntry[];
}

// ── AI Provider & Settings types ──────────────────────────────────────────────

export interface ApiKeyStatusResponse {
  has_groq_key: boolean;
  has_nvidia_key: boolean;
  has_openrouter_key?: boolean;
  has_anthropic_key?: boolean;
  has_custom_key: boolean;
  has_openai_compatible_key?: boolean;
  custom_ai_base_url?: string | null;
  custom_ai_model?: string | null;
  custom_ai_display_name?: string | null;
  openai_compatible_base_url?: string | null;
  openai_compatible_model?: string | null;
  openai_compatible_display_name?: string | null;
  has_anthropic_compatible_key?: boolean;
  anthropic_compatible_base_url?: string | null;
  anthropic_compatible_model?: string | null;
  anthropic_compatible_display_name?: string | null;
  preferred_ai_provider?: string | null;
  preferred_ai_model?: string | null;
}

export interface SaveApiKeysPayload {
  groq_api_key?: string;
  nvidia_api_key?: string;
  custom_ai_api_key?: string;
  custom_ai_base_url?: string;
  custom_ai_model?: string;
  custom_ai_display_name?: string;
  openai_compatible_api_key?: string;
  openai_compatible_base_url?: string;
  openai_compatible_model?: string;
  openai_compatible_display_name?: string;
  anthropic_compatible_api_key?: string;
  anthropic_compatible_base_url?: string;
  anthropic_compatible_model?: string;
  anthropic_compatible_display_name?: string;
  preferred_ai_provider?: string;
  preferred_ai_model?: string;
  anthropic_api_key?: string;
  openrouter_api_key?: string;
}

export interface TestConnectionPayload {
  provider: string;
  api_key?: string;
  base_url?: string;
  model?: string;
}

export interface TestConnectionResponse {
  status: "success" | "error";
  provider: string;
  model?: string;
  latency_ms?: number;
  message: string;
}

export interface CiSafetyGateStep {
  step: string;
  status: string;
  description: string;
}

export interface CiDeploymentInfo {
  is_configured: boolean;
  provider: string;
  display_name: string;
  status: string;
  connection_status?: "detected" | "connected" | "configured" | "unknown";
  deployment_url: string | null;
  preview_url?: string | null;
  detected_files: string[];
  description: string;
  recommendation: string;
  build_command?: string;
  output_dir?: string;
  target_branch?: string;
  framework?: string;
  required_env_vars?: string[];
  provider_dashboard_url?: string;
  can_manual_deploy?: boolean;
  latest_deploy_status?: string | null;
  latest_deploy_at?: string | null;
  safety_gates?: CiSafetyGateStep[];
}

export interface CiComponentInfo {
  name: string;
  path: string;
  ecosystem: string;
  framework: string;
  runtime_version: string;
  package_manager: string;
  lockfile: string | null;
  install_command: string;
  build_command: string | null;
  lint_command: string | null;
  test_command: string | null;
  has_test_suite: boolean;
  entry_point?: string | null;
  evidence: string[];
}

export interface CiEvidence {
  ecosystems: string[];
  components?: CiComponentInfo[];
  standalone_tests?: string[];
  has_python: boolean;
  has_node: boolean;
  has_rust: boolean;
  has_go: boolean;
  has_backend_dir: boolean;
  has_frontend_dir: boolean;
  has_pytest: boolean;
  has_npm_test: boolean;
  total_files: number;
}

export interface CiOverviewResponse {
  repo_id: string;
  repo_name: string;
  source_type: string;
  detected_ci: boolean;
  detected_ci_files: string[];
  needs_ci_setup: boolean;
  setup_status: "not_configured" | "proposed" | "awaiting_installation" | "installed";
  workflow_path: string;
  active_workflow_content: string | null;
  proposed_workflow_content: string | null;
  proposed_diff: string | null;
  pr_number: number | null;
  pr_url: string | null;
  branch_name: string | null;
  auto_fix_enabled: boolean;
  auto_commit_enabled: boolean;
  max_retry_budget: number;
  current_retry_count: number;
  last_run_id: string | null;
  last_run_status: string | null;
  last_run_conclusion: string | null;
  last_run_url: string | null;
  deployment: CiDeploymentInfo;
  evidence: CiEvidence;
}

export interface CiRunItem {
  run_id: string;
  run_number: number;
  name: string;
  path: string;
  event: string;
  status: string;
  conclusion: string | null;
  html_url: string;
  head_branch: string;
  head_sha: string;
  commit_message: string;
  created_at: string;
  updated_at: string;
}

export interface CiJobItem {
  job_id: string;
  name: string;
  status: string;
  conclusion: string | null;
  html_url: string;
  started_at: string;
  completed_at: string;
  steps: Array<{
    name: string;
    status: string;
    conclusion: string | null;
    number: number;
  }>;
  logs?: string;
}

export interface CiDiagnosisResult {
  is_fixable: boolean;
  category: string;
  status: string;
  failed_job: string;
  failed_step: string;
  diagnosis: string;
  proposed_patch: string;
  fingerprint: string;
  retry_count: number;
  retry_budget: number;
  log_snippet: string;
  message?: string;
}

export interface CiWorkflowPreviewResponse {
  repo_id: string;
  has_ci?: boolean;
  is_already_configured?: boolean;
  detected_ecosystems?: string[];
  detected_ci_files?: string[];
  needs_ci_setup?: boolean;
  workflow_path: string;
  workflow_filename?: string;
  workflow_content: string;
  diff_preview?: string;
  setup_status?: string;
  pr_url?: string;
  pr_number?: number;
  explanation: string;
}

export interface NvidiaModelMetadata {
  id: string;
  name: string;
  displayName?: string;
  context_length: number;
  capabilities: string[];
  description: string;
  recommended_for: string;
  badge?: string;
}

export interface NvidiaModelsResponse {
  provider: string;
  default_model: string;
  models: NvidiaModelMetadata[];
}

export interface AiModel {
  id: string;
  name: string;
  displayName: string;
  providerId: string;
  providerDisplayName: string;
  capabilities: string[];
  contextWindow: number;
  badge?: string;
  recommendedFor?: string;
  isCurated?: boolean;
  status: "available" | "unavailable" | "not_configured" | "deprecated" | "unknown";
  source?: string;
}

export interface AiProvider {
  id: string;
  displayName: string;
  type: string;
  priority: number;
  status: "available" | "not_configured" | "QUOTA_EXHAUSTED" | string;
  defaultModel?: string;
  models: AiModel[];
  quota?: {
    daily_limit: number;
    used_tokens: number;
    total_tokens?: number;
    remaining_tokens: number;
    percent_used: number;
    is_exhausted: boolean;
    warning: boolean;
    configured?: boolean;
  };
}

export interface ApinexQuotaResponse {
  provider: string;
  model: string;
  date: string;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  request_count: number;
  is_estimated: boolean;
  daily_limit: number;
  remaining_tokens: number;
  percent_used: number;
  is_exhausted: boolean;
  warning: boolean;
  warning_threshold: number;
  configured: boolean;
  updated_at?: string;
}

export interface MasterAiRegistryResponse {
  providers: Record<string, AiProvider>;
  preferredProvider: string;
  preferredModel: string;
}

export interface ModelForTaskResponse {
  provider: string;
  modelId: string;
  displayName: string;
  reason: string;
  fallbackChain: Array<{
    provider: string;
    modelId: string;
    displayName: string;
    reason: string;
  }>;
  healthStatus: string;
  task: string;
}

export interface GitStatusFile {
  path: string;
  status: "M" | "A" | "D" | "?" | "R";
  staged: boolean;
  additions: number;
  deletions: number;
}

export interface GitStatusResponse {
  repo_id: string;
  branch: string;
  clean: boolean;
  files: GitStatusFile[];
}

export interface GitCommitRequest {
  files: string[];
  message: string;
}

export interface GitCommitResponse {
  success: boolean;
  commit_sha: string;
  branch: string;
  message: string;
  files_committed: string[];
}

export interface GitCommitItem {
  sha: string;
  full_sha: string;
  message: string;
  author: string;
  date: string;
}

export interface GitHistoryResponse {
  repo_id: string;
  commits: GitCommitItem[];
}

export interface TerminalLine {
  index: number;
  text: string;
  stream: "stdout" | "stderr" | "system" | "command";
  timestamp: number;
}

export interface TerminalSessionItem {
  id: string;
  title: string;
  repo_id: string;
  cwd: string;
  rel_cwd?: string;
  prompt?: string;
  shell?: string;
  working_dir?: string;
  status: "idle" | "running" | "exited" | "closed";
  is_running?: boolean;
  pid?: number | null;
  current_command?: string | null;
  exit_code?: number | null;
  created_at: string;
  line_count: number;
  lines?: TerminalLine[];
  next_index?: number;
}



