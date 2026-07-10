import { Card, CardContent } from "@/components/ui/card"

export function ErrorNote({ message }: { message: string }) {
  return (
    <Card className="border-fail-ink/40 bg-fail-soft">
      <CardContent className="text-sm text-fail-ink" role="alert">
        {message}
      </CardContent>
    </Card>
  )
}
