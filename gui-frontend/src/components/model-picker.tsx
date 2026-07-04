import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ProviderIcon } from "@/components/brand"
import { api, type AiProvider } from "@/lib/api"

const CUSTOM = "__custom__"

/* Unified model selector: models grouped by AI provider (see the AI Providers
   page), filtered to providers whose kind maps to the given runtime, with a
   free-form fallback. */
export function ModelPicker({
  agent,
  providerId,
  model,
  onChange,
  placeholder,
}: {
  agent: string
  providerId?: string
  model: string
  onChange: (value: { providerId?: string; model: string; provider?: AiProvider }) => void
  placeholder?: string
}) {
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const eligible = useMemo(
    () =>
      (providersQuery.data?.providers ?? []).filter(
        (provider) => provider.agent === agent && provider.models.length > 0,
      ),
    [providersQuery.data, agent],
  )

  const match = providerId
    ? eligible.find((p) => p.id === providerId && p.models.includes(model))
    : eligible.find((p) => p.models.includes(model))
  const selected = match && model ? `${match.id}::${model}` : CUSTOM

  return (
    <div className="grid gap-1.5">
      <Select
        value={selected}
        onValueChange={(value) => {
          if (value === CUSTOM) {
            onChange({ providerId: undefined, model: "" })
            return
          }
          const [pid, ...rest] = value.split("::")
          const provider = eligible.find((item) => item.id === pid)
          onChange({ providerId: pid, model: rest.join("::"), provider })
        }}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {eligible.map((provider) => (
            <SelectGroup key={provider.id}>
              <SelectLabel className="flex items-center gap-1.5">
                <ProviderIcon provider={provider} size={13} /> {provider.name}
                {!provider.key_present && (
                  <span className="font-normal text-warn-ink">· key missing</span>
                )}
              </SelectLabel>
              {provider.models.map((item) => (
                <SelectItem
                  key={`${provider.id}::${item}`}
                  value={`${provider.id}::${item}`}
                  className="font-mono text-xs"
                >
                  {item}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
          {eligible.length > 0 && <SelectSeparator />}
          <SelectItem value={CUSTOM}>Custom model id…</SelectItem>
        </SelectContent>
      </Select>
      {selected === CUSTOM && (
        <Input
          className="font-mono"
          placeholder={placeholder ?? "model id (empty = runtime default)"}
          value={model}
          onChange={(event) => onChange({ providerId: undefined, model: event.target.value })}
        />
      )}
    </div>
  )
}
