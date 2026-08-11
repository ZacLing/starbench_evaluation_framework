import { ProviderIcon } from "@/components/brand"
import { cn } from "@/lib/utils"
import type { AiProvider } from "@/lib/api"

/* How a resolved provider authenticates: name, effective auth mode, and the
   credential source as a pass/warn chip ("KEY_ENV set/missing" for api_key
   providers, "CLI login" otherwise). One rendering shared by the profile
   editor and the wizard so the two surfaces can never disagree about whether
   a judge key is present. Callers own their no-provider fallback. */
export function CredentialStatus({
  provider,
  className,
}: {
  provider: AiProvider
  className?: string
}) {
  const mode = provider.auth === "cli_login" ? "global" : "env"
  const keyLabel = provider.api_key_env || "API key env"

  return (
    <div
      className={cn(
        "flex min-h-9 min-w-0 flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 text-xs",
        className,
      )}
    >
      <ProviderIcon provider={provider} size={14} />
      <span className="font-medium text-foreground">{provider.name}</span>
      <span className="font-mono text-muted-foreground">{mode}</span>
      {provider.auth === "api_key" ? (
        <span
          className={cn(
            "rounded px-1.5 py-0.5 font-mono text-[11px]",
            provider.key_present
              ? "bg-pass-soft text-pass-ink"
              : "bg-warn-soft text-warn-ink",
          )}
        >
          {keyLabel} {provider.key_present ? "set" : "missing"}
        </span>
      ) : (
        <span className="rounded bg-live-soft px-1.5 py-0.5 text-[11px] text-live-ink">
          CLI login
        </span>
      )}
    </div>
  )
}
