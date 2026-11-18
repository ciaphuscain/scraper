import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { BarChart3, ExternalLink, Play, RefreshCw } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Badge, Card, Checkbox, Input, Label, Progress } from "@/components/ui/primitives";
import { ErrorState, Loading } from "@/components/ui/states";
import { useChannel } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { fmtDate, relTime } from "@/lib/utils";
import { VideoTable } from "@/features/videos/VideoTable";
import { ChannelActions } from "./ChannelActions";

export function ChannelDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const { data: c, isLoading, error, refetch } = useChannel(id);
  const [since, setSince] = useState("");
  const full = useAction(() => api.post(`/api/channels/${id}/scan`, { full: true }), "Full rescan queued");
  const sinceScan = useAction(() => api.post(`/api/channels/${id}/scan`, { since }), "Scan queued");
  const pending = useAction(() => api.post<{ queued: number }>(`/api/channels/${id}/process-pending`), (r) => `Queued ${r.queued} video(s)`);
  const report = useAction(() => api.post(`/api/reports/channels/${id}`), "Channel report queued");
  const update = useAction((body: Record<string, unknown>) => api.patch(`/api/channels/${id}`, body), "Channel updated");

  if (isLoading) return <Loading />;
  if (error || !c) return <div className="p-6"><ErrorState error={error ?? "Not found"} onRetry={refetch} /></div>;
  return (
    <div className="pb-8">
      <PageHeader title={c.name}
        subtitle={<span className="flex items-center gap-2 font-mono text-xs">{c.handle} {c.id}
          <a href={c.url} target="_blank" rel="noreferrer" className="hover:text-fg"><ExternalLink className="size-3.5" /></a>
          {c.paused && <Badge tone="warn">Paused</Badge>}</span>}
        actions={<>
          <ChannelActions channel={c} onRemoved={() => nav("/channels")} />
          <Button variant="secondary" onClick={() => pending.mutate(undefined)}><Play />Process pending</Button>
          <Button variant="secondary" onClick={() => full.mutate(undefined)}><RefreshCw />Full rescan</Button>
          <Button variant="secondary" onClick={() => report.mutate(undefined)}><BarChart3 />Generate report</Button>
        </>} />
      <div className="space-y-4 px-6">
        <div className="grid gap-3 md:grid-cols-4">
          <Card className="p-4 md:col-span-2">
            <div className="flex items-start gap-4">
              {c.thumbnail_url && <img src={c.thumbnail_url} alt="" className="size-14 rounded-full object-cover" />}
              <p className="line-clamp-4 flex-1 text-sm text-muted">{c.description || "No description."}</p>
            </div>
            <div className="mt-3"><Progress value={c.progress} /><div className="mt-1 text-xs text-muted">{Math.round(c.progress * 100)}% processed · {c.pending} pending · {c.failed} failed · {c.unavailable} unavailable</div></div>
          </Card>
          <Card className="grid grid-cols-2 gap-2 p-4 text-sm">
            <div><div className="text-xs text-muted">Videos</div><div className="text-lg font-semibold">{c.videos}</div></div>
            <div><div className="text-xs text-muted">Shorts</div><div className="text-lg font-semibold">{c.shorts}</div></div>
            <div><div className="text-xs text-muted">Transcripts</div><div className="text-lg font-semibold">{c.transcripts}</div></div>
            <div><div className="text-xs text-muted">Ideas</div><div className="text-lg font-semibold">{c.ideas}</div></div>
          </Card>
          <Card className="space-y-1 p-4 text-xs text-muted">
            <div>Last scan: {relTime(c.last_scan_at)}</div>
            <div>Last successful sync: {relTime(c.last_sync_at)}</div>
            {c.last_scan_error && <div className="text-danger">{c.last_scan_error}</div>}
            {c.latest_report ? <Link className="block text-accent" to={`/reports?channel=${c.id}`}>Report from {fmtDate(c.latest_report.created_at)}</Link> : <div>No report yet</div>}
          </Card>
        </div>
        <Card className="flex flex-wrap items-end gap-4 p-4">
          <div className="space-y-1">
            <Label htmlFor="prio">Processing priority</Label>
            <Input id="prio" type="number" className="w-24" defaultValue={c.priority} onBlur={(e) => Number(e.target.value) !== c.priority && update.mutate({ priority: Number(e.target.value) })} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="since">Ignore uploads before</Label>
            <Input id="since" type="date" className="w-40" defaultValue={c.scan_since ? fmtDate(c.scan_since) : ""}
              onBlur={(e) => update.mutate(e.target.value ? { scan_since: e.target.value } : { clear_scan_since: true })} />
          </div>
          <label className="flex items-center gap-2 pb-1.5 text-sm"><Checkbox checked={c.auto_process} onChange={(e) => update.mutate({ auto_process: e.target.checked })} />Auto-collect transcripts for new uploads</label>
          <div className="ml-auto flex items-end gap-2">
            <div className="space-y-1"><Label htmlFor="scan-since">Scan only since</Label><Input id="scan-since" type="date" className="w-40" value={since} onChange={(e) => setSince(e.target.value)} /></div>
            <Button variant="secondary" disabled={!since} onClick={() => sinceScan.mutate(undefined)}>Scan</Button>
          </div>
        </Card>
        <VideoTable channelId={id} showChannel={false} />
      </div>
    </div>
  );
}
