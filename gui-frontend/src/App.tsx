import { Navigate, Route, Routes } from "react-router-dom"
import { Shell } from "@/components/shell"
import Dashboard from "@/pages/Dashboard"
import Tasks from "@/pages/Tasks"
import Providers from "@/pages/Providers"
import Runs from "@/pages/Runs"
import RunDetail from "@/pages/RunDetail"
import TaskDetail from "@/pages/TaskDetail"
import ExperimentDetail from "@/pages/ExperimentDetail"
import NewRun from "@/pages/NewRun"

export default function App() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/providers" element={<Providers />} />
        <Route path="/runs" element={<Runs />} />
        <Route path="/runs/:runId" element={<RunDetail />} />
        <Route path="/runs/:runId/tasks/:taskRunId" element={<TaskDetail />} />
        <Route path="/experiments/:experimentId" element={<ExperimentDetail />} />
        <Route path="/new" element={<NewRun />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
