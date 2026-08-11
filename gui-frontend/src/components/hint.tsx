import { CircleHelp } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/* Secondary "why / when to use" help behind a focusable question mark.
   Policy (docs/PRODUCT.md register): the essential meaning of a field must be
   inline (gloss text or self-describing enum options); the Hint carries only
   the second tier. Keyboard-focusable, so the help is not hover-only. */
export function Hint({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label="More about this field"
            className="inline-flex size-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <CircleHelp className="size-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-72 text-pretty">{children}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
