import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw, Trash2 } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Card, Input, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { useJobs, useSystem } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { JobRow, JOB_NAMES } from "./JobRow";

export function QueuePage() {
  const [sp] = useSearchParams();
  const [status, setStatus] = useState(sp.get("status") ?? "");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const sys = useSystem();
  const { data, isLoading, error, refetch } = useJobs({ status, job_type: type, page, page_size: 50 });
  const paused = sys.data?.queue_paused;
  const toggle = useAction(() => api.post(paused ? "/api/jobs/resume-all" : "/api/jobs/pause-all"), paused ? "Processing resumed" : "Processing paused");
  const retry = useAction(() => api.post<{ retried: number }>("/api/jobs/retry-failed"), (r) => `Retrying ${r.retried} job(s)`);
  const clear = useAction(() => api.post<{ deleted: number }>("/api/jobs/clear-finished"), (r) => `Removed ${r.deleted} finished job(s)`);
  const prio = useAction(({ id, p }: { id: number; p: number }) => api.put(`/api/jobs/${id}/priority`, { priority: p }), "Priority updated");
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div className="pb-8">
      <PageHeader title="Processing queue"
        subtitle={sys.data && !sys.data.worker.online ? <span className="text-danger">The worker is not running — jobs will wait until it starts (start.ps1).</span> : "Persistent job queue; survives restarts."}
        actions={<>
          <Button variant={paused ? "default" : "secondary"} onClick={() => toggle.mutate(undefined)}>{paused ? <><Play />Resume all</> : <><Pause />Pause all</>}</Button>
          <Button variant="secondary" onClick={() => retry.mutate(undefined)}><RotateCcw />Retry failed</Button>
          <Button variant="secondary" onClick={() => clear.mutate(undefined)}><Trash2 />Clear finished</Button>
        </>} />
      <div className="space-y-3 px-6">
        <div className="flex gap-2">
          <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            <option value="running">Running</option><option value="queued,retry_scheduled">Pending</option><option value="retry_scheduled">Retry scheduled</option>
            <option value="paused">Paused</option><option value="failed">Failed</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option>
          </Select>
          <Select aria-label="Job type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
            <option value="">All job types</option>{Object.entries(JOB_NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </div>
        {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
          <Card className="divide-y divide-border">
            {data?.jobs.length ? data.jobs.map((j) => (
              <div key={j.id} className="flex items-center">
                <div className="min-w-0 flex-1"><JobRow job={j} /></div>
                {["queued", "retry_scheduled", "paused"].includes(j.status) && (
                  <Input aria-label={`Priority for job ${j.id}`} type="number" title="Priority (higher runs first)" className="mr-3 w-16" defaultValue={j.priority}
                    onBlur={(e) => Number(e.target.value) !== j.priority && prio.mutate({ id: j.id, p: Number(e.target.value) })} />
                )}
              </div>
            )) : <Empty title="No jobs" />}
          </Card>
        )}
        {data && data.total > data.page_size && (
          <div className="flex items-center justify-end gap-2 text-xs text-muted">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
            Page {page} of {pages}
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
          </div>
        )}
      </div>
    </div>
  );
}
