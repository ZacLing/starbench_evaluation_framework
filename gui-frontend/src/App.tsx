import { lazy, Suspense } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { Shell } from "@/components/shell"

const Dashboard = lazy(() => import("@/pages/Dashboard"))
const Coverage = lazy(() => import("@/pages/Coverage"))
const Tasks = lazy(() => import("@/pages/Tasks"))
const Agents = lazy(() => import("@/pages/Agents"))
const Skills = lazy(() => import("@/pages/Skills"))
const Providers = lazy(() => import("@/pages/Providers"))
const Profiles = lazy(() => import("@/pages/Profiles"))
const Runs = lazy(() => import("@/pages/Runs"))
const RunDetail = lazy(() => import("@/pages/RunDetail"))
const TaskDetail = lazy(() => import("@/pages/TaskDetail"))
const ExperimentDetail = lazy(() => import("@/pages/ExperimentDetail"))
const NewRun = lazy(() => import("@/pages/NewRun"))

export default function App() {
  return (
    <Shell>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-md bg-muted" />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/coverage" element={<Coverage />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/profiles" element={<Profiles />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/providers" element={<Providers />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/runs/:runId/tasks/:taskRunId" element={<TaskDetail />} />
          <Route path="/experiments/:experimentId" element={<ExperimentDetail />} />
          <Route path="/new" element={<NewRun />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Shell>
  )
}
