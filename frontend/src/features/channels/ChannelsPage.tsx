import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Badge, Card, Checkbox, Input, Progress } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { StatusBadge } from "@/components/ui/status";
import { useChannels } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { relTime } from "@/lib/utils";
import { AddChannelDialog } from "./AddChannelDialog";
import { ChannelActions } from "./ChannelActions";

export function ChannelsPage() {
  const [showInactive, setShowInactive] = useState(false);
  const { data, isLoading, error, refetch } = useChannels(showInactive);
  const [add, setAdd] = useState(false);
  const [filter, setFilter] = useState("");
  const scanAll = useAction(() => api.post<{ job_ids: number[] }>("/api/channels/scan-all"), (r) => `Queued ${r.job_ids.length} scan(s)`);
  const restore = useAction((id: string) => api.post(`/api/channels/${id}/restore`), "Channel restored");
  const channels = useMemo(
    () => (data?.channels ?? []).filter((c) => !filter || `${c.name} ${c.handle ?? ""} ${c.id}`.toLowerCase().includes(filter.toLowerCase())),
    [data, filter],
  );
  return (
    <div className="pb-8">
      <PageHeader title="Channel library" subtitle={data ? `${data.channels.length} channel(s)` : undefined}
        actions={<>
          <Input aria-label="Filter channels" placeholder="Filter…" className="w-48" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <label className="flex items-center gap-1.5 text-xs text-muted"><Checkbox checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show removed</label>
          <Button variant="secondary" onClick={() => scanAll.mutate(undefined)}><RefreshCw />Refresh all</Button>
          <Button onClick={() => setAdd(true)}><Plus />Add channels</Button>
        </>} />
      <div className="space-y-4 px-6">
        {data?.pending_additions.length ? (
          <Card className="p-3 text-sm">
            <div className="mb-1 font-medium">Resolving channels</div>
            {data.pending_additions.map((j) => (
              <div key={j.id} className="flex items-center gap-2 text-xs text-muted">
                <StatusBadge status={j.status} /> <span className="font-mono">{String(j.payload.input_url ?? "")}</span>
                {j.error_message && <span className="text-danger">{j.error_message}</span>}
              </div>
            ))}
          </Card>
        ) : null}
        {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> : !channels.length ? (
          <Card><Empty title="No channels">Add YouTube channels to discover their videos and Shorts.<div className="mt-3"><Button size="sm" onClick={() => setAdd(true)}><Plus />Add channels</Button></div></Empty></Card>
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Channel</th>
                  <th className="px-2 py-2 font-medium">Videos</th>
                  <th className="px-2 py-2 font-medium">Shorts</th>
                  <th className="px-2 py-2 font-medium">Transcripts</th>
                  <th className="px-2 py-2 font-medium">Ideas</th>
                  <th className="px-2 py-2 font-medium">Failed</th>
                  <th className="w-40 px-2 py-2 font-medium">Progress</th>
                  <th className="px-2 py-2 font-medium">Last sync</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {channels.map((c) => (
                  <tr key={c.id} className="hover:bg-panel-2/50">
                    <td className="px-4 py-2">
                      <Link to={`/channels/${c.id}`} className="flex items-center gap-3">
                        {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" className="size-8 rounded-full object-cover" /> : <div className="size-8 rounded-full bg-panel-2" />}
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 font-medium">{c.name}{c.paused && <Badge tone="warn">Paused</Badge>}{!c.active && <Badge tone="muted">Removed</Badge>}</div>
                          <div className="font-mono text-[11px] text-muted">{c.handle ?? ""} {c.id}</div>
                        </div>
                      </Link>
                    </td>
                    <td className="px-2 tabular-nums">{c.videos}</td>
                    <td className="px-2 tabular-nums">{c.shorts}</td>
                    <td className="px-2 tabular-nums">{c.transcripts}</td>
                    <td className="px-2 tabular-nums">{c.ideas}</td>
                    <td className="px-2 tabular-nums">{c.failed ? <span className="text-danger">{c.failed}</span> : 0}</td>
                    <td className="px-2"><Progress value={c.progress} /><div className="mt-0.5 text-[11px] text-muted">{Math.round(c.progress * 100)}% · {c.pending} pending</div></td>
                    <td className="px-2 text-xs text-muted" title={c.last_scan_error ?? undefined}>{relTime(c.last_sync_at)}{c.last_scan_error && <div className="text-danger">scan error</div>}</td>
                    <td className="px-2">{c.active ? <ChannelActions channel={c} /> : <Button size="sm" variant="secondary" onClick={() => restore.mutate(c.id)}>Restore</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
      <AddChannelDialog open={add} onOpenChange={setAdd} />
    </div>
  );
}
