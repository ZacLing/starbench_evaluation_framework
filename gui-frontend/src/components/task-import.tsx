import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CheckCircle2, FolderPlus, Loader2, Upload, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { api, type ImportFile, type ImportReport } from "@/lib/api"
import { cn } from "@/lib/utils"

/* ---------- drag & drop task import ---------- */

async function entryToFiles(entry: FileSystemEntry, prefix: string): Promise<{ path: string; file: File }[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject),
    )
    return [{ path: `${prefix}${entry.name}`, file }]
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader()
    const children: FileSystemEntry[] = []
    // readEntries returns results in batches; drain it.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject),
      )
      if (!batch.length) break
      children.push(...batch)
    }
    const nested = await Promise.all(
      children.map((child) => entryToFiles(child, `${prefix}${entry.name}/`)),
    )
    return nested.flat()
  }
  return []
}

async function fileToImportFile(path: string, file: File): Promise<ImportFile> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
  return { path, content_b64: dataUrl.slice(dataUrl.indexOf(",") + 1) }
}

const MAX_FILES = 400

export function ImportDropzone({
  targetDir,
  onImported,
  compact,
}: {
  targetDir: string
  onImported: () => void
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<{ files: ImportFile[]; report: ImportReport } | null>(null)

  const handleFiles = async (collected: { path: string; file: File }[]) => {
    if (!collected.length) {
      toast.error("Nothing readable was dropped.")
      return
    }
    if (collected.length > MAX_FILES) {
      toast.error(`Too many files (${collected.length}); a task package should be small.`)
      return
    }
    setBusy(true)
    try {
      const files = await Promise.all(
        collected.map((item) => fileToImportFile(item.path, item.file)),
      )
      const report = await api.importTasks(targetDir, files, true)
      setPending({ files, report })
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const onDrop = async (event: React.DragEvent) => {
    event.preventDefault()
    setDragOver(false)
    const items = Array.from(event.dataTransfer.items)
    const entries = items
      .map((item) => item.webkitGetAsEntry?.())
      .filter((entry): entry is FileSystemEntry => Boolean(entry))
    if (entries.length) {
      const nested = await Promise.all(entries.map((entry) => entryToFiles(entry, "")))
      await handleFiles(nested.flat())
    } else {
      const files = Array.from(event.dataTransfer.files).map((file) => ({
        path: file.name,
        file,
      }))
      await handleFiles(files)
    }
  }

  const install = async () => {
    if (!pending) return
    setBusy(true)
    try {
      const report = await api.importTasks(targetDir, pending.files, false)
      toast.success(`Task ${report.task.id} imported.`)
      setPending(null)
      queryClient.invalidateQueries({ queryKey: ["tasklib"] })
      onImported()
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-2">
      <label
        className={cn(
          "grid cursor-pointer place-content-center gap-1 rounded-lg border-2 border-dashed text-center transition-colors",
          compact ? "px-4 py-5" : "px-6 py-10",
          dragOver ? "border-primary bg-accent" : "border-border hover:border-primary/50",
        )}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <Upload className="mx-auto size-5 text-muted-foreground" />
        <span className="text-sm font-medium">
          Drop a task folder or .zip here to import
        </span>
        <span className="text-xs text-muted-foreground">
          Needs task.json, prompt.md, and rubrics.json; validated before anything is written
        </span>
        <input
          type="file"
          className="sr-only"
          multiple
          onChange={async (event) => {
            const files = Array.from(event.target.files ?? []).map((file) => ({
              path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
              file,
            }))
            await handleFiles(files)
            event.target.value = ""
          }}
          // @ts-expect-error non-standard folder picker attribute
          webkitdirectory=""
        />
      </label>

      {busy && !pending && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Validating…
        </p>
      )}

      {pending && (
        <div
          className={cn(
            "rounded-md border p-3",
            pending.report.valid ? "border-pass-ink/30 bg-pass-soft/50" : "border-fail-ink/30 bg-fail-soft/50",
          )}
        >
          {pending.report.valid ? (
            <div className="grid gap-2">
              <p className="flex items-center gap-2 text-sm font-medium text-pass-ink">
                <CheckCircle2 className="size-4" />
                Valid package: {pending.report.task.id} · {pending.report.task.rubric_count}{" "}
                rubrics · {pending.report.file_count} files
              </p>
              {pending.report.warnings.map((warning) => (
                <p key={warning} className="text-xs text-warn-ink">
                  {warning}
                </p>
              ))}
              <div className="flex gap-2">
                <Button size="sm" disabled={busy} onClick={install}>
                  <FolderPlus /> Install into library
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid gap-1.5">
              <p className="flex items-center gap-2 text-sm font-medium text-fail-ink">
                <XCircle className="size-4" /> Not a valid task package
              </p>
              <ul className="grid gap-1 pl-6 text-xs text-fail-ink">
                {pending.report.errors.map((error) => (
                  <li key={error} className="list-disc">
                    {error}
                  </li>
                ))}
              </ul>
              <div>
                <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
                  Dismiss
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
