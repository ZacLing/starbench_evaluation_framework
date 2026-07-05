import { Link, NavLink, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Bot, Boxes, Gauge, Library, ListChecks, Plus, Puzzle, Star } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api"

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/tasks", label: "Task library", icon: Library, end: true },
  { to: "/agents", label: "Agents", icon: Bot, end: true },
  { to: "/skills", label: "Skills", icon: Puzzle, end: true },
  { to: "/providers", label: "AI providers", icon: Boxes, end: true },
  { to: "/runs", label: "Runs", icon: ListChecks, end: false },
  { to: "/new", label: "New experiment", icon: Plus, end: true },
]

export function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity })

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild tooltip="StarBench Console">
                <Link to="/">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                    <Star className="size-4" fill="currentColor" />
                  </span>
                  <span className="grid leading-tight">
                    <span className="font-semibold">StarBench</span>
                    <span className="text-xs text-muted-foreground">Console</span>
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <NavLink to={item.to} end={item.end}>
                      {({ isActive }) => (
                        <SidebarMenuButton isActive={isActive} tooltip={item.label} asChild>
                          <span>
                            <item.icon />
                            <span>{item.label}</span>
                          </span>
                        </SidebarMenuButton>
                      )}
                    </NavLink>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          {meta.data ? (
            <div
              className="truncate px-2 pb-1 font-mono text-xs text-muted-foreground group-data-[collapsible=icon]:hidden"
              title={meta.data.runs_dir}
            >
              {meta.data.runs_dir}
            </div>
          ) : null}
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur">
          <SidebarTrigger />
          <Separator orientation="vertical" className="!h-5" />
          <Crumbs pathname={location.pathname} />
          <div className="ml-auto">
            <Button asChild size="sm">
              <Link to="/new">
                <Plus /> New experiment
              </Link>
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 pb-16 md:p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}

function Crumbs({ pathname }: { pathname: string }) {
  const segments = pathname.split("/").filter(Boolean)
  const crumbs: { label: string; to?: string }[] = []
  if (segments.length === 0) crumbs.push({ label: "Dashboard" })
  else if (segments[0] === "new") crumbs.push({ label: "New experiment" })
  else if (segments[0] === "tasks") crumbs.push({ label: "Task library" })
  else if (segments[0] === "agents") crumbs.push({ label: "Agents" })
  else if (segments[0] === "skills") crumbs.push({ label: "Skills" })
  else if (segments[0] === "providers") crumbs.push({ label: "AI providers" })
  else if (segments[0] === "experiments") {
    crumbs.push({ label: "Runs", to: "/runs" })
    if (segments[1]) crumbs.push({ label: decodeURIComponent(segments[1]) })
  }
  else if (segments[0] === "runs") {
    crumbs.push({ label: "Runs", to: segments.length > 1 ? "/runs" : undefined })
    if (segments[1]) {
      const runId = decodeURIComponent(segments[1])
      crumbs.push({
        label: runId,
        to: segments.length > 2 ? `/runs/${segments[1]}` : undefined,
      })
    }
    if (segments[2] === "tasks" && segments[3]) {
      crumbs.push({ label: decodeURIComponent(segments[3]) })
    }
  }
  return (
    <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
      <ol className="flex items-center gap-1.5 overflow-hidden text-sm text-muted-foreground">
        {crumbs.map((crumb, index) => (
          <li key={index} className="flex min-w-0 items-center gap-1.5">
            {index > 0 && <span aria-hidden>/</span>}
            {crumb.to ? (
              <Link to={crumb.to} className="truncate font-mono hover:text-foreground">
                {crumb.label}
              </Link>
            ) : (
              <span className="truncate font-mono text-foreground" aria-current="page">
                {crumb.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  )
}
