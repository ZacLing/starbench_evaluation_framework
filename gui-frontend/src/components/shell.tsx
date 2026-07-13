import { Link, NavLink, useLocation } from "react-router-dom"
import { Bot, Boxes, Gauge, Grid3X3, Library, ListChecks, Plus, Puzzle, Ruler, Star, type LucideIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"

type NavEntry = { to: string; label: string; icon: LucideIcon; end: boolean }

// Primary destinations: the places an operator lives while a run is cooking.
const PRIMARY_NAV: NavEntry[] = [
  { to: "/", label: "Overview", icon: Gauge, end: true },
  { to: "/coverage", label: "Run matrix", icon: Grid3X3, end: true },
  { to: "/tasks", label: "Task library", icon: Library, end: true },
  { to: "/runs", label: "Runs", icon: ListChecks, end: false },
]

// Setup: the fixtures you configure once, then rarely touch mid-investigation.
const SETUP_NAV: NavEntry[] = [
  { to: "/profiles", label: "Profiles", icon: Ruler, end: true },
  { to: "/agents", label: "Agents", icon: Bot, end: true },
  { to: "/providers", label: "AI providers", icon: Boxes, end: true },
  { to: "/skills", label: "Skills", icon: Puzzle, end: true },
]

export function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation()

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
                {PRIMARY_NAV.map((item) => (
                  <NavItem key={item.to} item={item} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>

          <SidebarSeparator />

          <SidebarGroup>
            <SidebarGroupLabel className="text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Setup
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {SETUP_NAV.map((item) => (
                  <NavItem key={item.to} item={item} />
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
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

function NavItem({ item }: { item: NavEntry }) {
  return (
    <SidebarMenuItem>
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
  )
}

function Crumbs({ pathname }: { pathname: string }) {
  const segments = pathname.split("/").filter(Boolean)
  const crumbs: { label: string; to?: string }[] = []
  if (segments.length === 0) crumbs.push({ label: "Overview" })
  else if (segments[0] === "new") crumbs.push({ label: "New experiment" })
  else if (segments[0] === "coverage") crumbs.push({ label: "Run matrix" })
  else if (segments[0] === "tasks") crumbs.push({ label: "Task library" })
  else if (segments[0] === "profiles") crumbs.push({ label: "Profiles" })
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
