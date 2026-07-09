import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { compatibleProviders, ProviderIcon } from "@/components/brand"
import { api, type AiProvider, type ProviderFilter } from "@/lib/api"

const RUNTIME_DEFAULT = "__runtime_default__"

/* Execution-side model choice = a reference to (provider, model). Providers
   own endpoints, credentials, and catalogs; nothing is defined here. */
export function ProviderModelPicker({
  providerId,
  model,
  onChange,
  providerFilter,
  runtimeId,
  filter,
}: {
  providerId?: string
  model: string
  onChange: (value: { provider: AiProvider; model: string }) => void
  /** The runtime's provider filter (from /api/agents); undefined = show none. */
  providerFilter?: ProviderFilter
  /** Runtime id, used so CLI-login providers only appear for their owning CLI. */
  runtimeId?: string
  /** Extra narrowing on top of protocol compatibility. */
  filter?: (provider: AiProvider) => boolean
}) {
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const all = providersQuery.data?.providers ?? []
  const compatible = compatibleProviders(providerFilter, all, runtimeId)
  const providers = filter ? compatible.filter(filter) : compatible
  const provider = providers.find((item) => item.id === providerId)

  return (
    <div className="grid min-w-0 gap-2 sm:flex sm:flex-wrap sm:items-center">
      <Select
        value={providerId}
        onValueChange={(id) => {
          const next = providers.find((item) => item.id === id)
          if (next) onChange({ provider: next, model: next.models[0] ?? "" })
        }}
      >
        <SelectTrigger className="w-full sm:w-52">
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
        disabled={!provider && !model}
        onValueChange={(value) => {
          if (provider) onChange({ provider, model: value === RUNTIME_DEFAULT ? "" : value })
        }}
      >
        <SelectTrigger className="w-full font-mono text-xs sm:w-64">
          <SelectValue placeholder="Model…" />
        </SelectTrigger>
        <SelectContent>
          {(provider?.models ?? []).map((item) => (
            <SelectItem key={item} value={item} className="font-mono text-xs">
              {item}
            </SelectItem>
          ))}
          {/* A stored model id outside the provider's catalog (or with no
              provider selected at all) stays visible instead of blanking the
              control: the value is the truth, the catalog is a convenience. */}
          {model && (!provider || !provider.models.includes(model)) && (
            <SelectItem value={model} className="font-mono text-xs">
              {model}{" "}
              <span className="font-sans text-muted-foreground">
                {provider ? "· not in catalog" : "· stored value"}
              </span>
            </SelectItem>
          )}
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
