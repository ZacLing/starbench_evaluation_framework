import {
  Claude,
  ClaudeCode,
  DeepSeek,
  Doubao,
  Gemini,
  GeminiCLI,
  Grok,
  Kimi,
  OpenAI,
  OpenCode,
  Qwen,
} from "@lobehub/icons"
import { Plug } from "lucide-react"

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

export function AgentIcon({ agent, size = 20 }: { agent: string; size?: number }) {
  switch (agent) {
    case "claude":
      return <ClaudeCode size={size} />
    case "codex":
      return <OpenAI size={size} />
    case "gemini":
      return <GeminiCLI.Color size={size} />
    case "grok":
      return <Grok size={size} />
    case "opencode":
      return <OpenCode size={size} />
    default:
      return <Plug size={size} className="text-muted-foreground" />
  }
}

export const AGENT_TO_FAMILY: Record<string, FamilyId> = {
  claude: "claude",
  codex: "gpt",
  gemini: "gemini",
  grok: "grok",
  opencode: "compat",
}
