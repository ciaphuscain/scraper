import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Download, Film, Lightbulb, Play, Plus, RefreshCw } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { useDashboard } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { relTime } from "@/lib/utils";
import { AddChannelDialog, AddVideoDialog } from "@/features/channels/AddChannelDialog";
import { JobRow } from "@/features/processing/JobRow";

function Stat({ label, value, to }: { label: string; value: number | string; to?: string }) {
  const body = (
    <Card className="p-4 hover:border-accent/50">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </Card>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useDashboard();
  const [addCh, setAddCh] = useState(false);
  const [addVid, setAddVid] = useState(false);
  const nav = useNavigate();
  const scanAll = useAction(() => api.post<{ job_ids: number[] }>("/api/channels/scan-all"), (r) => `Queued ${r.job_ids.length} channel scan(s)`);
  const resume = useAction(() => api.post("/api/jobs/resume-all"), "Processing resumed");
  const exportAll = useAction(() => api.post("/api/exports", { scope: "all", format: "zip" }), "Archive export queued");

  return (
    <div className="pb-8">
      <PageHeader title="Dashboard" subtitle="Overview of your content archive and processing activity"
        actions={<>
          <Button onClick={() => setAddCh(true)}><Plus />Add channel</Button>
          <Button variant="secondary" onClick={() => setAddVid(true)}><Film />Add video</Button>
          <Button variant="secondary" onClick={() => scanAll.mutate(undefined)}><RefreshCw />Refresh channels</Button>
          <Button variant="secondary" onClick={() => resume.mutate(undefined)}><Play />Process pending</Button>
          <Button variant="secondary" onClick={() => nav("/ideas")}><Lightbulb />Idea explorer</Button>
          <Button variant="secondary" onClick={() => exportAll.mutate(undefined)}><Download />Export archive</Button>
        </>} />
      <div className="px-6">
        {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> : data && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
              <Stat label="Channels" value={data.channels} to="/channels" />
              <Stat label="Videos" value={data.videos} to="/videos?type=video" />
              <Stat label="Shorts" value={data.shorts} to="/videos?type=short" />
              <Stat label="Transcripts" value={data.transcripts} to="/videos?transcript=completed" />
              <Stat label="Analysed videos" value={data.analysed_videos} />
              <Stat label="Ideas" value={data.ideas} to="/ideas" />
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Stat label="Pending jobs" value={data.jobs.pending} to="/queue?status=queued,retry_scheduled" />
              <Stat label="Active jobs" value={data.jobs.active} to="/queue?status=running" />
              <Stat label="Paused" value={data.jobs.paused} to="/queue?status=paused" />
              <Stat label="Failed jobs" value={data.jobs.failed} to="/queue?status=failed" />
              <Stat label="Completed jobs" value={data.jobs.completed} to="/queue?status=completed" />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader><CardTitle>Current processing</CardTitle><Link className="text-xs text-accent" to="/queue">Open queue</Link></CardHeader>
                <div className="divide-y divide-border">
                  {data.active_jobs.length ? data.active_jobs.map((j) => <JobRow key={j.id} job={j} />) :
                    <Empty title="Nothing is running">{data.jobs.pending ? "Jobs are waiting — make sure the worker is running." : data.channels ? "All queued work is finished." : "Add a channel to start collecting transcripts."}</Empty>}
                </div>
              </Card>
              <Card>
                <CardHeader><CardTitle>Recently updated channels</CardTitle><Link className="text-xs text-accent" to="/channels">All channels</Link></CardHeader>
                <CardContent className="p-0">
                  {data.recent_channels.length ? (
                    <ul className="divide-y divide-border">
                      {data.recent_channels.map((c) => (
                        <li key={c.id}>
                          <Link to={`/channels/${c.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-panel-2">
                            {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" className="size-8 rounded-full object-cover" /> : <div className="size-8 rounded-full bg-panel-2" />}
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-medium">{c.name}</div>
                              <div className="text-xs text-muted">Last sync {relTime(c.last_sync_at)}</div>
                            </div>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : <Empty title="No channels yet"><Button size="sm" onClick={() => setAddCh(true)}><Plus />Add your first channel</Button></Empty>}
                </CardContent>
              </Card>
            </div>
            {data.recent_failures.length > 0 && (
              <Card>
                <CardHeader><CardTitle>Recent failures</CardTitle><Link className="text-xs text-accent" to="/queue?status=failed">View all</Link></CardHeader>
                <div className="divide-y divide-border">{data.recent_failures.map((j) => <JobRow key={j.id} job={j} />)}</div>
              </Card>
            )}
          </div>
        )}
      </div>
      <AddChannelDialog open={addCh} onOpenChange={setAddCh} />
      <AddVideoDialog open={addVid} onOpenChange={setAddVid} />
    </div>
  );
}
