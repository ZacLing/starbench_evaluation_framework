import {
  Anthropic,
  ByteDance,
  Claude,
  ClaudeCode,
  Codex,
  DeepSeek,
  Doubao,
  Gemini,
  GeminiCLI,
  Google,
  Grok,
  Kimi,
  OpenAI,
  OpenCode,
  OpenRouter,
  Qwen,
  Trae,
  Vercel,
} from "@lobehub/icons"
import { Plug, SquareTerminal } from "lucide-react"

/* Brand icons for model families and agent runtimes (lobe-icons, MIT). */

export type FamilyId = "claude" | "gpt" | "gemini" | "grok" | "compat"

/* OpenAI-compatible contenders carry the actual model vendor; show it when known. */
function modelVendorIcon(model: string, size: number): React.ReactNode | null {
  const id = model.toLowerCase()
  if (id.includes("doubao")) return <Doubao.Color size={size} />
  if (id.includes("qwen")) return <Qwen.Color size={size} />
  if (id.includes("deepseek")) return <DeepSeek.Color size={size} />
  if (id.includes("kimi") || id.includes("moonshot")) return <Kimi.Color size={size} />
  return null
}

export function FamilyIcon({
  family,
  model,
  size = 20,
}: {
  family: string
  model?: string
  size?: number
}) {
  if (model) {
    const vendor = modelVendorIcon(model, size)
    if (vendor) return vendor
  }
  switch (family) {
    case "claude":
      return <Claude.Color size={size} />
    case "gpt":
      return <OpenAI size={size} />
    case "gemini":
      return <Gemini.Color size={size} />
    case "grok":
      return <Grok size={size} />
    case "compat":
      return <OpenCode size={size} />
    default:
      return <Plug size={size} className="text-muted-foreground" />
  }
}

/* The contenders of every experiment are agent runtimes: full coding-agent
   CLIs (harness + tools + prompts + model), not bare models. */
export const AGENT_LABELS: Record<string, string> = {
  claude: "Claude Code",
  codex: "Codex",
  gemini: "Gemini CLI",
  grok: "Grok Build",
  opencode: "OpenCode",
}

export const AGENT_NOTES: Record<string, string> = {
  claude: "Anthropic's coding agent",
  codex: "OpenAI's coding agent",
  gemini: "Google's coding agent",
  grok: "xAI's coding agent",
  opencode: "Open-source agent for OpenAI-compatible models",
}

/* Icon hints a custom runtime can declare in its spec file (`icon` field). */
const CUSTOM_ICONS: Record<string, (size: number) => React.ReactNode> = {
  qwen: (size) => <Qwen.Avatar size={size} />,
  kimi: (size) => <Kimi.Avatar size={size} />,
  moonshot: (size) => <Kimi.Avatar size={size} />,
  trae: (size) => <Trae.Avatar size={size} />,
  bytedance: (size) => <ByteDance.Avatar size={size} />,
  deepseek: (size) => <DeepSeek.Avatar size={size} />,
  doubao: (size) => <Doubao.Avatar size={size} />,
  opencode: (size) => <OpenCode.Avatar size={size} />,
}

export const CUSTOM_ICON_CHOICES = ["", ...Object.keys(CUSTOM_ICONS)]

export function AgentIcon({
  agent,
  icon,
  size = 20,
}: {
  agent: string
  icon?: string | null
  size?: number
}) {
  switch (agent) {
    case "claude":
      return <ClaudeCode.Avatar size={size} />
    case "codex":
      return <Codex.Avatar size={size} />
    case "gemini":
      return <GeminiCLI.Avatar size={size} />
    case "grok":
      return <Grok.Avatar size={size} />
    case "opencode":
      return <OpenCode.Avatar size={size} />
  }
  if (agent.startsWith("custom:")) {
    const render = icon ? CUSTOM_ICONS[icon.toLowerCase()] : undefined
    if (render) return render(size)
    return <SquareTerminal size={size} className="text-muted-foreground" />
  }
  return <Plug size={size} className="text-muted-foreground" />
}

/* Runtime <-> provider compatibility is decided by wire protocol, not vendor.
   Every runtime accepts every provider that speaks its protocol:
   - Claude Code: Anthropic protocol (official, or any anthropic_base_url) via env
   - Codex: OpenAI Responses protocol (official, or any OpenAI-compatible
     gateway) via config overrides in the codex bin prefix
   - OpenCode: OpenAI protocol via gateway flags
   - Gemini CLI: Gemini protocol (official, or any gemini_base_url) via env
   - Grok Build: official only (the CLI has no endpoint override mechanism) */
const OPENAI_PROTOCOL_KINDS = new Set(["openai-compatible", "openai", "xai"])

interface CompatProvider {
  kind: string
  anthropic_base_url?: string | null
  gemini_base_url?: string | null
}

export function compatibleProviders<T extends CompatProvider>(
  runtime: string,
  providers: T[],
  protocol?: string | null,
): T[] {
  if (runtime.startsWith("custom:")) {
    switch (protocol ?? "none") {
      case "openai":
        return providers.filter((provider) => OPENAI_PROTOCOL_KINDS.has(provider.kind))
      case "anthropic":
        return providers.filter(
          (provider) => provider.kind === "anthropic" || Boolean(provider.anthropic_base_url),
        )
      case "gemini":
        return providers.filter(
          (provider) => provider.kind === "google" || Boolean(provider.gemini_base_url),
        )
      default:
        // protocol "none": the CLI uses its own login/config; no provider applies.
        return []
    }
  }
  switch (runtime) {
    case "claude":
      return providers.filter(
        (provider) => provider.kind === "anthropic" || Boolean(provider.anthropic_base_url),
      )
    case "opencode":
      return providers.filter((provider) => OPENAI_PROTOCOL_KINDS.has(provider.kind))
    case "codex":
      return providers.filter(
        (provider) => provider.kind === "openai" || provider.kind === "openai-compatible",
      )
    case "gemini":
      return providers.filter(
        (provider) => provider.kind === "google" || Boolean(provider.gemini_base_url),
      )
    case "grok":
      return providers.filter((provider) => provider.kind === "xai")
    default:
      return providers
  }
}

export const DEFAULT_OPENAI_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  xai: "https://api.x.ai/v1",
}

export const AGENT_TO_FAMILY: Record<string, FamilyId> = {
  claude: "claude",
  codex: "gpt",
  gemini: "gemini",
  grok: "grok",
  opencode: "compat",
}

export function ProviderIcon({
  provider,
  size = 20,
}: {
  provider: { id: string; name: string; kind: string }
  size?: number
}) {
  const id = `${provider.id} ${provider.name}`.toLowerCase()
  if (id.includes("vercel")) return <Vercel size={size} />
  if (id.includes("openrouter")) return <OpenRouter size={size} />
  const vendor = modelVendorIcon(id, size)
  if (vendor) return vendor
  switch (provider.kind) {
    case "anthropic":
      return <Anthropic size={size} />
    case "openai":
      return <OpenAI size={size} />
    case "google":
      return <Google.Color size={size} />
    case "xai":
      return <Grok size={size} />
    default:
      return <OpenCode size={size} />
  }
}
