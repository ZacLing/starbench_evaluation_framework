import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ProviderIcon } from "@/components/brand"
import { api, type AiProvider } from "@/lib/api"

const RUNTIME_DEFAULT = "__runtime_default__"

/* Execution-side model choice = a reference to (provider, model). Providers
   own endpoints, credentials, and catalogs; nothing is defined here. */
export function ProviderModelPicker({
  providerId,
  model,
  onChange,
  agent,
}: {
  providerId?: string
  model: string
  onChange: (value: { provider: AiProvider; model: string }) => void
  /** Restrict the provider list to providers compatible with this runtime. */
  agent?: string
}) {
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const providers = (providersQuery.data?.providers ?? []).filter(
    (item) => !agent || item.agent === agent,
  )
  const provider = providers.find((item) => item.id === providerId)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={providerId}
        onValueChange={(id) => {
          const next = providers.find((item) => item.id === id)
          if (next) onChange({ provider: next, model: next.models[0] ?? "" })
        }}
      >
        <SelectTrigger className="w-52">
          <SelectValue placeholder="Provider…" />
        </SelectTrigger>
        <SelectContent>
          {providers.map((item) => (
            <SelectItem key={item.id} value={item.id}>
              <span className="flex items-center gap-2">
                <ProviderIcon provider={item} size={14} />
                {item.name}
                {item.auth === "api_key" && !item.key_present && (
                  <span className="text-xs text-warn-ink">· key missing</span>
                )}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={model || RUNTIME_DEFAULT}
        disabled={!provider}
        onValueChange={(value) => {
          if (provider) onChange({ provider, model: value === RUNTIME_DEFAULT ? "" : value })
        }}
      >
        <SelectTrigger className="w-64 font-mono text-xs">
          <SelectValue placeholder="Model…" />
        </SelectTrigger>
        <SelectContent>
          {(provider?.models ?? []).map((item) => (
            <SelectItem key={item} value={item} className="font-mono text-xs">
              {item}
            </SelectItem>
          ))}
          <SelectItem value={RUNTIME_DEFAULT} className="text-xs text-muted-foreground">
            (runtime default)
          </SelectItem>
        </SelectContent>
      </Select>

      {provider && provider.models.length === 0 && (
        <span className="text-xs text-muted-foreground">
          No catalog yet —{" "}
          <Link to="/providers" className="text-primary hover:underline">
            refresh it on the AI providers page
          </Link>
        </span>
      )}
    </div>
  )
}
