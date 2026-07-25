import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RuntimeOptionRow } from "@/lib/api"

/* Auto-rendered runtime knob controls, driven by the adapter registry's option
   declarations (served through /api/agents). Only user-surface knobs matching
   the given role are shown; wiring-surface options (gateway provider/base_url/
   api_key_env) are transport and never rendered. An empty string means unset —
   planning's option cleaner drops it.

   Per YAGNI only the integer/string input paths exist today (max_turns is the
   sole declared user knob). The enum (Select) and boolean (Switch) paths arrive
   with the first adapter that declares such a user option; the declaration
   types already carry the shape so the backend contract stays complete. */
export function RuntimeOptionFields({
  declarations,
  role,
  values,
  onChange,
}: {
  declarations: RuntimeOptionRow[]
  role: "executor" | "evaluator"
  values: Record<string, string | number | boolean>
  onChange: (name: string, value: string) => void
}) {
  const visible = declarations.filter(
    (option) => option.surface === "user" && (option.role === role || option.role === "both"),
  )
  if (!visible.length) return null
  return (
    <>
      {visible.map((option) => (
        <div key={option.name} className="grid gap-1.5">
          <Label htmlFor={`opt-${role}-${option.name}`}>{option.label || option.name}</Label>
          <Input
            id={`opt-${role}-${option.name}`}
            type={option.type === "integer" ? "number" : "text"}
            value={String(values[option.name] ?? "")}
            onChange={(event) => onChange(option.name, event.target.value)}
          />
          {option.help ? (
            <p className="text-xs text-muted-foreground">{option.help}</p>
          ) : null}
        </div>
      ))}
    </>
  )
}
