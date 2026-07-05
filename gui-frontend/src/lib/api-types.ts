/* GENERATED — do not edit.
 * Source: src/starbench/gui/contracts.py — regenerate with `make gen-types`.
 */

export type ProviderKind = "anthropic" | "openai" | "google" | "xai" | "openai-compatible"

export type RuntimeProtocol = "openai" | "anthropic" | "gemini" | "xai" | "none"

export type AuthKind = "api_key" | "cli_login"

export type ModelsSource = "api" | "catalog"

export interface RuntimeCli {
  bin: string
  present: boolean
  path: string | null
}

export interface ProviderFilter {
  kinds: string[]
  accepts_anthropic_endpoint: boolean
  accepts_gemini_endpoint: boolean
}

export interface BuiltinRuntime {
  id: string
  label: string
  note: string
  protocol: "openai" | "anthropic" | "gemini" | "xai" | "none"
  docker_capable: boolean
  docker_image: string
  builtin: true
  cli: RuntimeCli
  provider_filter: ProviderFilter
}

export interface CustomRuntime {
  id: string
  spec_id: string
  builtin: false
  source_path: string
  error: string | null
  label?: string
  description?: string
  icon?: string
  protocol?: "openai" | "anthropic" | "gemini" | "xai" | "none"
  provider_filter?: ProviderFilter
  base_url_env?: string
  api_key_env?: string
  command?: string
  args?: string[]
  judge_args?: string[]
  judge_args_inherited?: boolean
  model_flag?: string | null
  prompt_via?: string
  prompt_flag?: string
  parser?: string
  env?: Record<string, string>
  docker_image?: string | null
  docker_env_passthrough?: string[]
  docker_capable?: boolean
  cli?: RuntimeCli
}

export interface AgentsPayload {
  runtimes_dir: string
  builtin: BuiltinRuntime[]
  custom: CustomRuntime[]
}

export interface AiProvider {
  id: string
  name: string
  kind: "anthropic" | "openai" | "google" | "xai" | "openai-compatible"
  auth: "api_key" | "cli_login"
  base_url: string
  api_key_env: string
  models: string[]
  models_fetched_at: string | null
  models_source: "api" | "catalog" | null
  agent: string
  key_present: boolean
  anthropic_base_url?: string | null
  gemini_base_url?: string | null
}

export interface ProvidersPayload {
  providers: AiProvider[]
  persisted?: boolean
}

export interface ExperimentPlanItem {
  label: string
  agent: string
  model: string
  run_id: string
  backend: string
  backend_downgraded: boolean
  warnings: string[]
  argv: string[]
  docker_image?: string
}

export interface Contender {
  agent: string
  provider_id: string
  model: string
  label?: string
  thinking_effort?: string
}
