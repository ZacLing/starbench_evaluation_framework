import { useCallback, useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  Check,
  CheckCircle2,
  ChevronRight,
  CornerLeftUp,
  Edit3,
  FolderOpen,
  FolderPlus,
  Loader2,
  Search,
  Upload,
  XCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { api, type DirListing, type ImportFile, type ImportReport } from "@/lib/api"
import { cn } from "@/lib/utils"

/* ---------- server-side directory picker ---------- */

const LAST_DIRECTORY_PICKER_PATH = "starbench:last-directory-picker-path"

function safeStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeStorageSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // Private browsing and restricted storage should not break folder browsing.
  }
}

function parentPath(path?: string | null): string | null {
  if (!path) return null
  const normalized = path.replace(/\/+$/, "") || "/"
  if (normalized === "/") return null
  const index = normalized.lastIndexOf("/")
  if (index <= 0) return "/"
  return normalized.slice(0, index)
}

interface PathCrumb {
  label: string
  path: string
  title?: string
}

function crumbsForPath(path?: string | null): PathCrumb[] {
  if (!path) return []
  const normalized = path.replace(/\/+$/, "") || "/"
  if (normalized === "/") return [{ label: "/", path: "/" }]
  const parts = normalized.split("/").filter(Boolean)
  const crumbs = [{ label: "/", path: "/" }]
  let cursor = ""
  for (const part of parts) {
    cursor += `/${part}`
    crumbs.push({ label: part, path: cursor })
  }
  return crumbs
}

function compactCrumbs(crumbs: PathCrumb[]): PathCrumb[] {
  if (crumbs.length <= 6) return crumbs
  const hiddenParent = crumbs[crumbs.length - 5]
  return [
    crumbs[0],
    { label: "…", path: hiddenParent.path, title: hiddenParent.path },
    ...crumbs.slice(-4),
  ]
}

function taskPackageLabel(count: number) {
  return `${count} task package${count === 1 ? "" : "s"}`
}

export function DirectoryPickerDialog({
  open,
  onOpenChange,
  onSelect,
  initialPath,
  title = "Choose a folder",
  description = "Browse folders on this machine.",
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (path: string) => void
  initialPath?: string | null
  title?: string
  description?: string
}) {
  const [listing, setListing] = useState<DirListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [editingPath, setEditingPath] = useState(false)
  const [pathDraft, setPathDraft] = useState("")
  const [filter, setFilter] = useState("")

  const load = useCallback(async (path?: string | null) => {
    setLoading(true)
    try {
      const next = await api.browse(path)
      setListing(next)
      setPathDraft(next.path)
      setEditingPath(false)
      setFilter("")
      safeStorageSet(LAST_DIRECTORY_PICKER_PATH, next.path)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      const stored = safeStorageGet(LAST_DIRECTORY_PICKER_PATH)
      load(listing?.path ?? stored ?? parentPath(initialPath) ?? initialPath ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const crumbs = compactCrumbs(crumbsForPath(listing?.path))
  const normalizedFilter = filter.trim().toLowerCase()
  const visibleDirs =
    listing?.dirs.filter((dir) => {
      if (!normalizedFilter) return true
      return (
        dir.name.toLowerCase().includes(normalizedFilter) ||
        dir.path.toLowerCase().includes(normalizedFilter)
      )
    }) ?? []
  const showFilter = Boolean(listing && listing.dirs.length >= 8)
  const footerNote = listing
    ? listing.task_count > 0
      ? "Ready to register this task folder."
      : "No task packages here yet; you can still register it and import later."
    : "Choose a folder to register."
  const useLabel =
    listing && listing.task_count > 0
      ? `Use this folder — ${taskPackageLabel(listing.task_count)}`
      : "Use this folder"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="min-w-0 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="grid min-w-0 gap-2">
          {editingPath ? (
            <form
              className="flex min-w-0 items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                const nextPath = pathDraft.trim()
                if (nextPath) load(nextPath)
              }}
            >
              <Input
                autoFocus
                value={pathDraft}
                onChange={(event) => setPathDraft(event.target.value)}
                className="font-mono text-xs"
                placeholder="/absolute/path/to/tasks"
              />
              <Button size="sm" type="submit" disabled={loading || !pathDraft.trim()}>
                {loading ? <Loader2 className="animate-spin" /> : <Check />}
                Go
              </Button>
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={() => {
                  setPathDraft(listing?.path ?? "")
                  setEditingPath(false)
                }}
              >
                Cancel
              </Button>
            </form>
          ) : (
            <div className="flex min-w-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!listing?.parent || loading}
                onClick={() => load(listing?.parent)}
              >
                <CornerLeftUp /> Up
              </Button>
              <div className="min-w-0 flex-1 overflow-hidden rounded-md border bg-muted/50 px-2 py-1.5">
                {crumbs.length ? (
                  <div className="flex min-w-0 items-center gap-1 font-mono text-xs">
                    {crumbs.map((crumb, index) => (
                      <span key={`${crumb.path}-${index}`} className="flex min-w-0 items-center gap-1">
                        {index > 0 && <ChevronRight className="size-3 text-muted-foreground" />}
                        <button
                          type="button"
                          className={cn(
                            "max-w-40 truncate rounded px-1.5 py-0.5 text-foreground hover:bg-background focus:outline-none focus:ring-2 focus:ring-ring/50",
                            (index === 0 || index === crumbs.length - 1 || crumb.label === "…") &&
                              "shrink-0",
                            index === crumbs.length - 1 && "bg-background font-medium",
                          )}
                          title={crumb.title ?? crumb.path}
                          disabled={loading || crumb.path === listing?.path}
                          onClick={() => load(crumb.path)}
                        >
                          {crumb.label}
                        </button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="font-mono text-xs text-muted-foreground">Loading…</span>
                )}
              </div>
              <Button
                variant="outline"
                size="icon-sm"
                type="button"
                disabled={!listing}
                onClick={() => {
                  setPathDraft(listing?.path ?? "")
                  setEditingPath(true)
                }}
                aria-label="Edit path"
                title="Edit path"
              >
                <Edit3 />
              </Button>
            </div>
          )}

          {showFilter && (
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                className="pl-8"
                placeholder={`Filter ${listing?.dirs.length ?? 0} folders`}
              />
            </div>
          )}

          <ScrollArea className="h-[300px] w-full min-w-0 rounded-md border">
            <div className="grid gap-0.5 p-1">
              {loading && !listing ? (
                <div className="grid place-content-center py-10 text-muted-foreground">
                  <Loader2 className="animate-spin" />
                </div>
              ) : visibleDirs.length ? (
                visibleDirs.map((dir) => (
                  <button
                    key={dir.path}
                    type="button"
                    onClick={() => load(dir.path)}
                    className="flex min-h-10 w-full items-center gap-2 rounded px-2 text-left text-sm hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring/50"
                  >
                    <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{dir.name}</span>
                    {dir.task_count > 0 && (
                      <span className="rounded-full bg-pass-soft px-2 py-0.5 text-xs text-pass-ink">
                        {dir.task_count} tasks
                      </span>
                    )}
                    <ChevronRight className="size-3.5 text-muted-foreground" />
                  </button>
                ))
              ) : (
                <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                  {normalizedFilter ? "No folders match this filter." : "No subfolders here."}
                </p>
              )}
            </div>
          </ScrollArea>
        </div>
        <DialogFooter className="w-full min-w-0 items-stretch gap-3 sm:items-center sm:justify-between">
          <p
            className={cn(
              "min-w-0 flex-1 text-xs",
              listing?.task_count ? "text-pass-ink" : "text-muted-foreground",
            )}
          >
            {footerNote}
          </p>
          <div className="flex shrink-0 flex-col-reverse gap-2 sm:flex-row">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              disabled={!listing}
              onClick={() => {
                if (listing) {
                  safeStorageSet(LAST_DIRECTORY_PICKER_PATH, listing.path)
                  onSelect(listing.path)
                  onOpenChange(false)
                }
              }}
            >
              {useLabel}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

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
