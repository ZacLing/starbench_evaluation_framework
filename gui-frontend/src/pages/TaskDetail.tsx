import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useParams, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  Brain,
  ChevronRight,
  FileText,
  Hash,
  Link as LinkIcon,
  MessageSquare,
  SquareTerminal,
  Zap,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ExecBadge, RubricBadge, VariantBadge } from "@/components/verdict"
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type ArtifactManifest,
  type JudgeAggregate,
  type OutputsListing,
  type TaskRunDetail,
  type TraceEntry,
  type VariantSibling,
} from "@/lib/api"
import { fmtDuration, fmtTime } from "@/lib/format"
import { renderMarkdown } from "@/lib/markdown"
import { cn } from "@/lib/utils"

/* Sentinel path for the pinned "Final message" deliverable. */
const FINAL_MESSAGE = "\0final-message"

/* The app routes with HashRouter, so a bare #e42 fragment would clobber the
   route. Shareable trace anchors ride the route's search string instead:
   …#/runs/<run>/tasks/<task>?e=42 */
function parseTraceParam(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null
  return Number(value)
}

export default function TaskDetail() {
  const { runId = "", taskRunId = "" } = useParams()
  const [searchParams] = useSearchParams()
  const taskQuery = useQuery({
    queryKey: ["task", runId, taskRunId],
    queryFn: () => api.task(runId, taskRunId),
  })
  /* Deep links like ?e=42 land on the Trace tab; everything else keeps the
     verdict-first habit (conclusion first, process on demand). */
  const [tab, setTab] = useState<string>(() =>
    parseTraceParam(searchParams.get("e")) !== null ? "trace" : "verdicts",
  )
  const [selectedPath, setSelectedPath] = useState<string | null>(null)

  /* Route params can change without unmounting this page (e.g. jumping to a
     sibling variant) — reset per-task view state when they do. */
  useEffect(() => {
    setTab(parseTraceParam(searchParams.get("e")) !== null ? "trace" : "verdicts")
    setSelectedPath(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, taskRunId])

  const openDeliverable = useCallback((path: string) => {
    setSelectedPath(path)
    setTab("deliverables")
  }, [])

  if (taskQuery.isPending) return <Skeleton className="h-96" />
  if (taskQuery.isError) return <ErrorNote message={(taskQuery.error as Error).message} />

  const detail = taskQuery.data
  const executor = detail.executor ?? {}
  const rubricCount =
    detail.judges.single?.aggregate.total_count ??
    detail.judges.parallel?.aggregate.total_count ??
    null
  const deliverableCount =
    detail.artifact_manifest?.file_count ?? detail.outputs_listing?.file_count ?? 0

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h1 className="break-all font-mono text-xl font-semibold tracking-tight">
            {detail.run_task_id}
          </h1>
          <p className="text-sm text-muted-foreground">
            {detail.task_id ?? "unknown task"}
            {executor.started_at && ` · started ${fmtTime(executor.started_at)}`}
            {` · ${fmtDuration(executor.duration_seconds)}`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <VariantBadge variant={detail.instruction_variant} />
          <ExecBadge status={executor.status} timedOut={executor.timed_out} />
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="trace">
            Trace{detail.raw_event_count > 0 && <TabCount value={detail.raw_event_count} />}
          </TabsTrigger>
          <TabsTrigger value="deliverables">
            Deliverables{deliverableCount > 0 && <TabCount value={deliverableCount} />}
          </TabsTrigger>
          <TabsTrigger value="verdicts">
            Verdicts{rubricCount !== null && <TabCount value={rubricCount} />}
          </TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>

        {/* forceMount + hidden keeps loaded trace pages and the selected
            deliverable alive across tab switches (evidence → file → back). */}
        <TabsContent
          value="trace"
          forceMount
          className="mt-4 grid gap-4 data-[state=inactive]:hidden"
        >
          <TracePane key={`${runId}/${taskRunId}`} detail={detail} runId={runId} taskRunId={taskRunId} />
        </TabsContent>
        <TabsContent
          value="deliverables"
          forceMount
          className="mt-4 data-[state=inactive]:hidden"
        >
          <DeliverablesPane
            key={`${runId}/${taskRunId}`}
            detail={detail}
            runId={runId}
            taskRunId={taskRunId}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
          />
        </TabsContent>
        <TabsContent value="verdicts" className="mt-4 grid gap-4">
          <VerdictsPane detail={detail} onOpenArtifact={openDeliverable} />
        </TabsContent>
        <TabsContent value="logs" className="mt-4 grid gap-4">
          <LogsPane detail={detail} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function TabCount({ value }: { value: number }) {
  return <span className="ml-1 text-xs text-muted-foreground tabular-nums">{value}</span>
}

/* ---------- trace ---------- */

const TRACE_PAGE = 200
/* Cap on automatic page loads while chasing a #eNN anchor. */
const TRACE_AUTOLOAD_PAGES = 20

const TRACE_KIND: Record<
  TraceEntry["type"],
  { label: string; icon: typeof Zap; ink: string }
> = {
  command: { label: "command", icon: SquareTerminal, ink: "text-foreground" },
  reasoning: { label: "reasoning", icon: Brain, ink: "text-muted-foreground" },
  message: { label: "message", icon: MessageSquare, ink: "text-foreground" },
  file_change: { label: "file change", icon: FileText, ink: "text-foreground" },
  lifecycle: { label: "lifecycle", icon: Zap, ink: "text-muted-foreground" },
  other: { label: "other", icon: Hash, ink: "text-muted-foreground" },
}

function TracePane({
  detail,
  runId,
  taskRunId,
}: {
  detail: TaskRunDetail
  runId: string
  taskRunId: string
}) {
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [entries, setEntries] = useState<TraceEntry[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(0)
  const [total, setTotal] = useState<number | null>(null)
  const [hasEvents, setHasEvents] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(false)
  const targetIndex = useRef<number | null>(parseTraceParam(searchParams.get("e")))
  const autoloads = useRef(0)

  const shareAnchor = useCallback(
    (index: number) => {
      setSearchParams({ e: String(index) }, { replace: true })
      const base = window.location.href.split("#")[0]
      const url = `${base}#${location.pathname}?e=${index}`
      void navigator.clipboard?.writeText(url).catch(() => {})
      toast.success(`Link to event #${index} copied`)
    },
    [location.pathname, setSearchParams],
  )

  const loadMore = useCallback(async () => {
    if (nextOffset === null || loading) return
    setLoading(true)
    try {
      const page = await api.trace(runId, taskRunId, nextOffset, TRACE_PAGE)
      setEntries((current) => [...current, ...page.entries])
      setNextOffset(page.next_offset)
      setTotal(page.total)
      setHasEvents(page.has_events)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [runId, taskRunId, nextOffset, loading])

  useEffect(() => {
    if (hasEvents === null && !loading) void loadMore()
  }, [hasEvents, loading, loadMore])

  /* Chase a #eNN deep link: keep loading pages until the anchor exists, then
     scroll it into view once. */
  useEffect(() => {
    const target = targetIndex.current
    if (target === null || !entries.length) return
    if (entries.length > target) {
      targetIndex.current = null
      requestAnimationFrame(() => {
        document.getElementById(`e${target}`)?.scrollIntoView({ block: "center" })
      })
    } else if (nextOffset !== null && autoloads.current < TRACE_AUTOLOAD_PAGES) {
      autoloads.current += 1
      void loadMore()
    }
  }, [entries, nextOffset, loadMore])

  if (hasEvents === false) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No event stream was captured for this task run (logs/events.jsonl is missing).
        </CardContent>
      </Card>
    )
  }

  const trace = detail.trace_summary
  const toolCalls =
    (trace?.item_type_counts?.command_execution ?? 0) +
    (trace?.item_type_counts?.file_change ?? 0)
  const usageEntries = Object.entries(trace?.usage ?? {}).filter(
    ([, value]) => typeof value === "number",
  ) as [string, number][]

  return (
    <>
      <div className="flex flex-wrap gap-2">
        <StatChip label="events" value={String(total ?? detail.raw_event_count)} />
        {trace ? (
          <StatChip label="tool calls" value={String(toolCalls)} />
        ) : (
          <StatChip label="trace summary" value="missing" />
        )}
        {detail.executor?.duration_seconds !== undefined && (
          <StatChip label="duration" value={fmtDuration(detail.executor.duration_seconds)} />
        )}
        {usageEntries.map(([key, value]) => (
          <StatChip key={key} label={key.replace(/_/g, " ")} value={value.toLocaleString()} />
        ))}
      </div>

      <Card className="gap-0 overflow-hidden py-0">
        <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
          <span className="text-sm font-semibold">Timeline</span>
          {total !== null && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {entries.length} of {total}
            </span>
          )}
        </div>
        {entries.length === 0 && loading && <Skeleton className="m-4 h-40" />}
        <div className="divide-y">
          {entries.map((entry) => (
            <TraceRow key={entry.index} entry={entry} onShare={shareAnchor} />
          ))}
        </div>
        {nextOffset !== null && entries.length > 0 && (
          <div className="border-t px-4 py-3">
            <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadMore()}>
              {loading ? "Loading…" : `Load more (${(total ?? 0) - entries.length} left)`}
            </Button>
          </div>
        )}
      </Card>

      <RawEvents runId={runId} taskRunId={taskRunId} total={detail.raw_event_count} />
    </>
  )
}

function TraceRow({ entry, onShare }: { entry: TraceEntry; onShare: (index: number) => void }) {
  const kind = TRACE_KIND[entry.type] ?? TRACE_KIND.other
  const Icon = kind.icon
  const anchorId = `e${entry.index}`
  /* The body earns an expander when it says more than the title already does. */
  const expandable =
    entry.body.length > 0 &&
    (entry.type === "command" ||
      entry.type === "other" ||
      entry.type === "lifecycle" ||
      entry.body.trim() !== entry.title.trim())

  const header = (
    <div className="flex min-w-0 items-baseline gap-2">
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onShare(entry.index)
        }}
        className="group/anchor flex shrink-0 cursor-pointer items-baseline gap-1 font-mono text-[11px] text-muted-foreground tabular-nums hover:text-foreground"
        title={`Copy link to event #${entry.index}`}
      >
        <LinkIcon className="size-2.5 self-center opacity-0 transition-opacity group-hover/anchor:opacity-100" />
        #{entry.index}
      </button>
      <Icon className={cn("size-3.5 shrink-0 self-center", kind.ink)} aria-hidden />
      <span className="shrink-0 text-[11px] uppercase tracking-wide text-muted-foreground">
        {kind.label}
      </span>
      <span
        className={cn(
          "min-w-0 truncate text-sm",
          entry.type === "command" && "font-mono",
          (entry.type === "reasoning" || entry.type === "lifecycle") && "text-muted-foreground",
        )}
        title={entry.title}
      >
        {entry.title || "–"}
      </span>
      {entry.seconds_offset !== null && entry.seconds_offset !== undefined && (
        <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">
          +{entry.seconds_offset}s
        </span>
      )}
    </div>
  )

  if (!expandable) {
    return (
      <div id={anchorId} className={cn("px-4 py-2", entry.type === "reasoning" && "bg-muted/30")}>
        {header}
      </div>
    )
  }

  return (
    <details
      id={anchorId}
      className={cn("group px-4 py-2", entry.type === "reasoning" && "bg-muted/30")}
      open={entry.type === "message"}
    >
      <summary className="flex cursor-pointer list-none items-baseline gap-2 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3 shrink-0 self-center text-muted-foreground transition-transform group-open:rotate-90" />
        <div className="min-w-0 flex-1">{header}</div>
      </summary>
      <div className="mt-2 pl-5">
        <pre
          className={cn(
            "max-h-96 overflow-auto rounded-md border bg-muted/40 px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap",
            entry.type === "message" && "font-sans text-sm",
            entry.type === "reasoning" && "font-sans",
          )}
        >
          {entry.body}
        </pre>
        {entry.truncated && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            Truncated to 20 KB — full text in Raw JSONL below.
          </p>
        )}
      </div>
    </details>
  )
}

function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border bg-card px-2.5 py-1 text-xs">
      <span className="uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono font-medium tabular-nums">{value}</span>
    </span>
  )
}

function RawEvents({
  runId,
  taskRunId,
  total,
}: {
  runId: string
  taskRunId: string
  total: number
}) {
  const [events, setEvents] = useState<Record<string, unknown>[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(0)
  const [loading, setLoading] = useState(false)

  const loadMore = async () => {
    if (nextOffset === null) return
    setLoading(true)
    try {
      const page = await api.events(runId, taskRunId, nextOffset)
      setEvents((current) => [...current, ...page.events])
      setNextOffset(page.next_offset)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
        <span className="text-sm font-semibold">Raw JSONL</span>
        <span className="text-xs text-muted-foreground tabular-nums">{total}</span>
        <span className="text-xs text-muted-foreground">
          unnormalized events, straight off disk
        </span>
        {(events.length === 0 || nextOffset !== null) && total > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-7"
            disabled={loading}
            onClick={loadMore}
          >
            {loading ? "Loading…" : events.length ? `Load more (${total - events.length} left)` : "Load raw events"}
          </Button>
        )}
      </div>
      {events.length > 0 && (
        <div className="divide-y">
          {events.map((event, index) => (
            <details key={index} className="group px-4 py-2">
              <summary className="cursor-pointer list-none font-mono text-xs text-muted-foreground">
                <ChevronRight className="mr-1 inline size-3 transition-transform group-open:rotate-90" />
                #{index} {String((event as { type?: string }).type ?? "event")}
              </summary>
              <pre className="mt-2 overflow-auto rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed">
                {JSON.stringify(event, null, 2)}
              </pre>
            </details>
          ))}
        </div>
      )}
    </Card>
  )
}

/* ---------- deliverables ---------- */

interface FileEntry {
  path: string
  size_bytes?: number | null
}

function collectFiles(
  manifest: ArtifactManifest | null,
  listing: OutputsListing | null,
): { files: FileEntry[]; fromListing: boolean; listingTruncated: boolean } {
  if (manifest) {
    return {
      files: manifest.entries
        .filter((entry) => entry.kind === "file")
        .map((entry) => ({ path: entry.path, size_bytes: entry.size_bytes })),
      fromListing: false,
      listingTruncated: false,
    }
  }
  if (listing) {
    return {
      files: listing.entries
        .filter((entry) => entry.kind === "file")
        .map((entry) => ({ path: entry.path ?? "", size_bytes: entry.size_bytes })),
      fromListing: true,
      listingTruncated: listing.truncated,
    }
  }
  return { files: [], fromListing: false, listingTruncated: false }
}

function fmtBytes(size: number | null | undefined): string {
  if (size === null || size === undefined) return "?"
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function variantLabel(sibling: VariantSibling, group: VariantSibling[]): string {
  const variant = sibling.instruction_variant ?? "?"
  const peers = group.filter((item) => item.instruction_variant === sibling.instruction_variant)
  if (peers.length <= 1) return variant
  return `${variant} · ${peers.indexOf(sibling) + 1}`
}

function DeliverablesPane({
  detail,
  runId,
  taskRunId,
  selectedPath,
  onSelect,
}: {
  detail: TaskRunDetail
  runId: string
  taskRunId: string
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  const { files, fromListing, listingTruncated } = useMemo(
    () => collectFiles(detail.artifact_manifest, detail.outputs_listing),
    [detail.artifact_manifest, detail.outputs_listing],
  )
  /* Which sibling task run the drawer reads from (variant switcher). */
  const [viewTaskRunId, setViewTaskRunId] = useState(taskRunId)
  const selected = selectedPath ?? FINAL_MESSAGE
  const group = detail.variant_group

  /* Group files by directory for the tree. */
  const grouped = useMemo(() => {
    const dirs = new Map<string, FileEntry[]>()
    for (const file of files) {
      const slash = file.path.lastIndexOf("/")
      const dir = slash === -1 ? "" : file.path.slice(0, slash)
      const bucket = dirs.get(dir) ?? []
      bucket.push(file)
      dirs.set(dir, bucket)
    }
    return [...dirs.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [files])

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(220px,300px)_minmax(0,1fr)]">
      <Card className="gap-0 overflow-hidden py-0">
        <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
          <span className="text-sm font-semibold">Files</span>
          <span className="text-xs text-muted-foreground tabular-nums">{files.length}</span>
        </div>
        {fromListing && (
          <p className="border-b bg-warn-soft/50 px-4 py-2 text-xs text-warn-ink">
            Artifact manifest missing — listing workspace/outputs/ from disk
            {listingTruncated ? " (truncated at 500 entries)" : ""}.
          </p>
        )}
        <div className="grid py-1">
          <FileButton
            label="Final message"
            icon={<MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />}
            selected={selected === FINAL_MESSAGE}
            onClick={() => onSelect(FINAL_MESSAGE)}
          />
          {grouped.map(([dir, bucket]) => (
            <div key={dir || "."}>
              {dir && (
                <div
                  className="truncate px-4 pt-2 pb-0.5 font-mono text-[11px] text-muted-foreground"
                  title={dir}
                >
                  {dir}/
                </div>
              )}
              {bucket.map((file) => (
                <FileButton
                  key={file.path}
                  label={file.path.slice(dir ? dir.length + 1 : 0)}
                  meta={fmtBytes(file.size_bytes)}
                  icon={<FileText className="size-3.5 shrink-0 text-muted-foreground" />}
                  selected={selected === file.path}
                  indent={Boolean(dir)}
                  onClick={() => onSelect(file.path)}
                />
              ))}
            </div>
          ))}
          {files.length === 0 && (
            <p className="px-4 py-6 text-sm text-muted-foreground">
              {detail.artifact_manifest || detail.outputs_listing
                ? "The delivered outputs directory is empty."
                : "No artifact manifest and no outputs directory on disk."}
            </p>
          )}
        </div>
      </Card>

      <Card className="min-w-0 gap-0 overflow-hidden py-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-muted/30 px-4 py-2.5">
          <span
            className="min-w-0 flex-1 truncate font-mono text-sm font-medium"
            title={selected === FINAL_MESSAGE ? "Final message" : selected}
          >
            {selected === FINAL_MESSAGE ? "Final message" : selected}
          </span>
          {group.length > 1 && (
            <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Variant">
              {group.map((sibling) => (
                <Button
                  key={sibling.run_task_id}
                  size="sm"
                  variant={sibling.run_task_id === viewTaskRunId ? "default" : "outline"}
                  className="h-6 px-2 font-mono text-xs"
                  title={sibling.run_task_id}
                  onClick={() => setViewTaskRunId(sibling.run_task_id)}
                >
                  {variantLabel(sibling, group)}
                </Button>
              ))}
            </div>
          )}
        </div>
        {viewTaskRunId !== taskRunId && (
          <p className="border-b bg-live-soft/50 px-4 py-2 text-xs text-live-ink">
            Viewing variant <span className="font-mono">{viewTaskRunId}</span> —{" "}
            <a
              className="underline underline-offset-2"
              href={`#/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(viewTaskRunId)}`}
            >
              open its full page
            </a>
          </p>
        )}
        <ArtifactViewer runId={runId} taskRunId={viewTaskRunId} path={selected} detail={detail} />
      </Card>
    </div>
  )
}

function FileButton({
  label,
  meta,
  icon,
  selected,
  indent,
  onClick,
}: {
  label: string
  meta?: string
  icon: React.ReactNode
  selected: boolean
  indent?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full min-w-0 items-center gap-2 px-4 py-1.5 text-left text-sm hover:bg-muted/60",
        indent && "pl-7",
        selected && "bg-muted font-medium",
      )}
      title={label}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{label}</span>
      {meta && (
        <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular-nums">
          {meta}
        </span>
      )}
    </button>
  )
}

function ArtifactViewer({
  runId,
  taskRunId,
  path,
  detail,
}: {
  runId: string
  taskRunId: string
  path: string
  detail: TaskRunDetail
}) {
  const isFinal = path === FINAL_MESSAGE
  const isSelf = taskRunId === detail.run_task_id

  /* Final message of a sibling variant comes from its task detail. */
  const siblingQuery = useQuery({
    queryKey: ["task", runId, taskRunId],
    queryFn: () => api.task(runId, taskRunId),
    enabled: isFinal && !isSelf,
  })
  const artifactQuery = useQuery({
    queryKey: ["artifact", runId, taskRunId, path],
    queryFn: () => api.artifact(runId, taskRunId, path),
    enabled: !isFinal,
    retry: false,
  })

  if (isFinal) {
    if (!isSelf && siblingQuery.isPending) return <Skeleton className="m-4 h-40" />
    const message = isSelf ? detail.final_message : siblingQuery.data?.final_message
    if (!message) {
      return (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">
          No final message captured{isSelf ? "" : " for this variant"}.
        </p>
      )
    }
    return (
      <div
        className="prose-starbench max-w-[76ch] px-5 py-4"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(message) }}
      />
    )
  }

  if (artifactQuery.isPending) return <Skeleton className="m-4 h-40" />
  if (artifactQuery.isError) {
    return (
      <p className="px-4 py-8 text-center text-sm text-muted-foreground">
        {(artifactQuery.error as Error).message}
      </p>
    )
  }
  const artifact = artifactQuery.data
  if (artifact.is_binary || artifact.content === null) {
    return (
      <div className="grid gap-1 px-5 py-6 text-sm">
        <div className="font-mono">{artifact.path}</div>
        <div className="text-muted-foreground">
          {fmtBytes(artifact.size_bytes)} ·{" "}
          {artifact.is_binary
            ? "binary file — not rendered"
            : "exceeds the 1 MB preview limit — open it from the run directory on disk"}
        </div>
      </div>
    )
  }
  if (path.toLowerCase().endsWith(".md")) {
    return (
      <div
        className="prose-starbench max-w-[76ch] px-5 py-4"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(artifact.content) }}
      />
    )
  }
  return (
    <pre className="max-h-[640px] overflow-auto px-5 py-4 font-mono text-xs leading-relaxed">
      {artifact.content}
    </pre>
  )
}

/* ---------- verdicts ---------- */

function VerdictsPane({
  detail,
  onOpenArtifact,
}: {
  detail: TaskRunDetail
  onOpenArtifact: (path: string) => void
}) {
  const artifactPaths = useMemo(
    () =>
      new Set(
        (detail.artifact_manifest?.entries ?? detail.outputs_listing?.entries ?? [])
          .filter((entry) => entry.kind === "file" && entry.path)
          .map((entry) => entry.path as string),
      ),
    [detail.artifact_manifest, detail.outputs_listing],
  )
  const modes = (["single", "parallel"] as const).filter((mode) => detail.judges[mode])
  if (!modes.length) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No judge results yet.{" "}
          {detail.evaluated ? "" : "This task run has not been evaluated."}
        </CardContent>
      </Card>
    )
  }
  return (
    <>
      {modes.map((mode) => (
        <JudgePanel
          key={mode}
          mode={mode}
          aggregate={detail.judges[mode]!.aggregate}
          status={detail.judges[mode]!.status}
          questions={detail.rubric_questions}
          artifactPaths={artifactPaths}
          onOpenArtifact={onOpenArtifact}
        />
      ))}
    </>
  )
}

function JudgePanel({
  mode,
  aggregate,
  status,
  questions,
  artifactPaths,
  onOpenArtifact,
}: {
  mode: string
  aggregate: JudgeAggregate
  status: { status?: string; duration_seconds?: number } | null
  questions: Record<string, string>
  artifactPaths: Set<string>
  onOpenArtifact: (path: string) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-4 py-3">
        <span className="text-sm font-semibold capitalize">{mode} judge</span>
        {aggregate.overall_pass ? (
          <Badge className="border-transparent bg-pass-soft text-pass-ink">
            ✓ Pass · {aggregate.passed_count}/{aggregate.total_count}
          </Badge>
        ) : (
          <Badge className="border-transparent bg-fail-soft text-fail-ink">
            ✕ Fail · {aggregate.passed_count}/{aggregate.total_count}
          </Badge>
        )}
        {aggregate.fail_fast_failures.length > 0 && (
          <Badge className="border-transparent bg-fail-soft text-fail-ink">
            fail-fast: {aggregate.fail_fast_failures.join(", ")}
          </Badge>
        )}
        {aggregate.missing.length > 0 && (
          <Badge className="border-transparent bg-warn-soft text-warn-ink">
            missing: {aggregate.missing.join(", ")}
          </Badge>
        )}
        {status?.status && (
          <span className="ml-auto text-xs text-muted-foreground">
            judge {status.status} · {fmtDuration(status.duration_seconds)}
          </span>
        )}
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-8" />
            <TableHead>Rubric</TableHead>
            <TableHead className="w-full">Question</TableHead>
            <TableHead>Expected</TableHead>
            <TableHead>Answer</TableHead>
            <TableHead>Verdict</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {aggregate.results.map((row) => {
            const isOpen = expanded.has(row.rubric_id)
            /* fail-fast rows carry a warning edge; a tripped one is the red
               line that sank the whole verdict, so it shouts louder. */
            const failFastTripped = row.fail_fast && !row.passed
            return [
              <TableRow
                key={row.rubric_id}
                className={cn(
                  "cursor-pointer",
                  row.fail_fast && "border-l-2 border-l-warn-ink/50",
                  failFastTripped && "border-l-fail-ink bg-fail-soft/40 hover:bg-fail-soft/60",
                )}
                onClick={() => toggle(row.rubric_id)}
              >
                <TableCell>
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-label={`Toggle evidence for ${row.rubric_id}`}
                    className="grid size-6 place-content-center rounded text-muted-foreground hover:bg-muted"
                    onClick={(event) => {
                      event.stopPropagation()
                      toggle(row.rubric_id)
                    }}
                  >
                    <ChevronRight
                      className={cn("size-4 transition-transform", isOpen && "rotate-90")}
                    />
                  </button>
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-sm font-medium">
                  {row.rubric_id}
                  {row.fail_fast && (
                    <Badge
                      variant="outline"
                      className={cn(
                        "ml-1.5 px-1 text-[10px] text-muted-foreground",
                        failFastTripped && "border-fail-ink/40 text-fail-ink",
                      )}
                      title="fail-fast rubric"
                    >
                      ff
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="max-w-[52ch] text-sm">
                  {questions[row.rubric_id] ?? (
                    <span className="text-muted-foreground">question not in manifest</span>
                  )}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.expected ? "Yes" : "No"}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.answer === null || row.answer === undefined
                    ? "–"
                    : row.answer
                      ? "Yes"
                      : "No"}
                </TableCell>
                <TableCell>
                  <RubricBadge passed={row.passed} />
                </TableCell>
              </TableRow>,
              isOpen ? (
                <TableRow key={`${row.rubric_id}-evidence`} className="hover:bg-transparent">
                  <TableCell
                    colSpan={6}
                    className={cn("bg-muted/40 px-6 py-4", failFastTripped && "bg-fail-soft/30")}
                  >
                    <div className="max-w-[72ch]">
                      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Judge evidence
                      </div>
                      {row.evidence ? (
                        <blockquote className="whitespace-pre-wrap border-l-2 pl-3 text-sm leading-relaxed">
                          <EvidenceText
                            text={row.evidence}
                            artifactPaths={artifactPaths}
                            onOpenArtifact={onOpenArtifact}
                          />
                        </blockquote>
                      ) : (
                        <p className="text-sm text-muted-foreground">
                          The judge did not record evidence for this rubric.
                        </p>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ) : null,
            ]
          })}
        </TableBody>
      </Table>
    </Card>
  )
}

/* Matches outputs/-relative references the judge tends to quote:
   outputs/x.md, ./workspace/outputs/sub/y.txt, … */
const ARTIFACT_REF = /(?:\.\/)?(?:workspace\/)?outputs\/([\w./-]+)/g

function EvidenceText({
  text,
  artifactPaths,
  onOpenArtifact,
}: {
  text: string
  artifactPaths: Set<string>
  onOpenArtifact: (path: string) => void
}) {
  const nodes: React.ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(ARTIFACT_REF)) {
    const start = match.index ?? 0
    /* Trim trailing sentence punctuation out of the candidate path. */
    let candidate = match[1]
    while (candidate && ".,;:!?)".includes(candidate[candidate.length - 1])) {
      candidate = candidate.slice(0, -1)
    }
    if (!artifactPaths.has(candidate)) continue
    const matchedLength = match[0].length - (match[1].length - candidate.length)
    if (start > cursor) nodes.push(text.slice(cursor, start))
    nodes.push(
      <button
        key={`${start}-${candidate}`}
        type="button"
        className="font-mono text-live-ink underline underline-offset-2 hover:opacity-80"
        title={`Open ${candidate} in Deliverables`}
        onClick={(event) => {
          event.stopPropagation()
          onOpenArtifact(candidate)
        }}
      >
        {text.slice(start, start + matchedLength)}
      </button>,
    )
    cursor = start + matchedLength
  }
  if (!nodes.length) return <>{text}</>
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

/* ---------- logs ---------- */

function LogsPane({ detail }: { detail: TaskRunDetail }) {
  const executor = detail.executor
  return (
    <>
      <Card>
        <CardContent className="grid gap-4">
          {executor ? (
            <dl className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-6 gap-y-3">
              {(
                [
                  ["status", executor.status],
                  ["exit code", executor.exit_code],
                  ["timed out", executor.timed_out],
                  ["started", executor.started_at],
                  ["ended", executor.ended_at],
                  ["duration", fmtDuration(executor.duration_seconds)],
                ] as [string, unknown][]
              )
                .filter(([, value]) => value !== undefined && value !== null)
                .map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">{key}</dt>
                    <dd className="break-all font-mono text-sm">{String(value)}</dd>
                  </div>
                ))}
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">No executor status recorded.</p>
          )}
          {Array.isArray(executor?.command) && (
            <pre className="overflow-auto rounded-md border bg-muted/50 px-3 py-2 font-mono text-xs leading-relaxed">
              {executor.command.join(" ")}
            </pre>
          )}
        </CardContent>
      </Card>
      <Card className="gap-0 overflow-hidden py-0">
        <div className="border-b bg-muted/30 px-4 py-2.5 text-sm font-semibold">stderr tail</div>
        {detail.stderr_tail ? (
          <pre className="max-h-[480px] overflow-auto bg-muted/40 px-4 py-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {detail.stderr_tail}
          </pre>
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">stderr.log is empty or absent.</p>
        )}
      </Card>
    </>
  )
}
