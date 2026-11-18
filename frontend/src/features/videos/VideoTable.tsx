import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, Checkbox, Input, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { StatusBadge, TypeBadge } from "@/components/ui/status";
import { useVideos } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/services/api";
import { fmtDate, fmtTs } from "@/lib/utils";

export type VideoFilters = {
  q: string; video_type: string; transcript_status: string; analysis_status: string; date_from: string; date_to: string; sort: string;
};

export const emptyFilters: VideoFilters = { q: "", video_type: "", transcript_status: "", analysis_status: "", date_from: "", date_to: "", sort: "newest" };

export function VideoTable({ channelId, initial, showChannel = true }: { channelId?: string; initial?: Partial<VideoFilters>; showChannel?: boolean }) {
  const [f, setF] = useState<VideoFilters>({ ...emptyFilters, ...initial });
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const q = useDebounced(f.q);
  const pageSize = 50;
  const { data, isLoading, error, refetch, isFetching } = useVideos({ ...f, q, channel_id: channelId, page, page_size: pageSize });
  const set = (k: keyof VideoFilters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(1); };
  const batch = useAction(({ action, priority }: { action: string; priority?: number }) =>
    api.post<{ affected: number }>("/api/videos/batch", { ids: [...sel], action, priority }), (r) => `${r.affected} video(s) updated`);
  const exportSel = useAction(() => api.post("/api/exports", { scope: "videos", ids: [...sel], format: "zip" }), "Export queued — see Exports");
  const vids = data?.videos ?? [];
  const allSel = vids.length > 0 && vids.every((v) => sel.has(v.id));
  const toggleAll = () => {
    const n = new Set(sel);
    vids.forEach((v) => (allSel ? n.delete(v.id) : n.add(v.id)));
    setSel(n);
  };
  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Search videos" placeholder="Search titles & descriptions…" className="w-64" value={f.q} onChange={set("q")} />
        <Select aria-label="Type" value={f.video_type} onChange={set("video_type")}>
          <option value="">All types</option><option value="video">Videos</option><option value="short">Shorts</option><option value="live">Live</option>
        </Select>
        <Select aria-label="Transcript status" value={f.transcript_status} onChange={set("transcript_status")}>
          <option value="">Any transcript</option><option value="completed">Transcribed</option><option value="pending">Pending</option>
          <option value="queued,in_progress">In progress</option><option value="failed">Failed</option><option value="unavailable">Unavailable</option>
        </Select>
        <Select aria-label="Analysis status" value={f.analysis_status} onChange={set("analysis_status")}>
          <option value="">Any analysis</option><option value="completed">Analysed</option><option value="pending">Not analysed</option>
          <option value="queued,in_progress">In progress</option><option value="failed">Failed</option>
        </Select>
        <Input aria-label="From date" type="date" className="w-36" value={f.date_from} onChange={set("date_from")} />
        <Input aria-label="To date" type="date" className="w-36" value={f.date_to} onChange={set("date_to")} />
        <Select aria-label="Sort" value={f.sort} onChange={set("sort")}>
          <option value="newest">Newest</option><option value="oldest">Oldest</option><option value="title">Title</option>
          <option value="duration">Longest</option><option value="ideas">Most ideas</option><option value="discovered">Recently discovered</option>
        </Select>
      </div>
      {sel.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-sm">
          <span className="font-medium">{sel.size} selected</span>
          <Button size="sm" onClick={() => batch.mutate({ action: "process" })}>Collect transcripts</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "analyze" })}>Extract ideas</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "reprocess" })}>Re-fetch transcripts</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "retry" })}>Retry failed</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "priority", priority: 50 })}>Prioritise</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "deselect" })}>Exclude</Button>
          <Button size="sm" variant="secondary" onClick={() => batch.mutate({ action: "select" })}>Include</Button>
          <Button size="sm" variant="secondary" onClick={() => exportSel.mutate(undefined)}><Download />Export</Button>
          <Button size="sm" variant="ghost" onClick={() => setSel(new Set())}>Clear</Button>
        </div>
      )}
      {isLoading ? <Loading /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Card className="overflow-x-auto">
          {!vids.length ? <Empty title="No videos match">Adjust filters, or add a channel and wait for discovery to complete.</Empty> : (
            <table className="w-full text-sm">
              <thead className="border-b border-border text-left text-xs text-muted">
                <tr>
                  <th className="w-8 px-3 py-2"><Checkbox aria-label="Select all on page" checked={allSel} onChange={toggleAll} /></th>
                  <th className="px-2 py-2 font-medium">Video</th>
                  {showChannel && <th className="px-2 py-2 font-medium">Channel</th>}
                  <th className="px-2 py-2 font-medium">Uploaded</th>
                  <th className="px-2 py-2 font-medium">Duration</th>
                  <th className="px-2 py-2 font-medium">Type</th>
                  <th className="px-2 py-2 font-medium">Transcript</th>
                  <th className="px-2 py-2 font-medium">AI</th>
                  <th className="px-2 py-2 font-medium">Ideas</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {vids.map((v) => (
                  <tr key={v.id} className={v.selected ? "hover:bg-panel-2/50" : "opacity-50 hover:bg-panel-2/50"}>
                    <td className="px-3"><Checkbox aria-label={`Select ${v.title}`} checked={sel.has(v.id)} onChange={() => { const n = new Set(sel); n.has(v.id) ? n.delete(v.id) : n.add(v.id); setSel(n); }} /></td>
                    <td className="px-2 py-1.5">
                      <Link to={`/videos/${v.id}`} className="flex items-center gap-2.5">
                        {v.thumbnail_url ? <img src={v.thumbnail_url} alt="" loading="lazy" className="h-9 w-16 shrink-0 rounded object-cover" /> : <div className="h-9 w-16 shrink-0 rounded bg-panel-2" />}
                        <span className="line-clamp-2 max-w-md font-medium hover:text-accent">{v.title || v.id}</span>
                      </Link>
                    </td>
                    {showChannel && <td className="px-2 text-xs text-muted">{v.channel_name ?? "–"}</td>}
                    <td className="px-2 text-xs tabular-nums text-muted" title={v.upload_date_approximate ? "approximate" : undefined}>{fmtDate(v.upload_date)}{v.upload_date_approximate ? " ~" : ""}</td>
                    <td className="px-2 text-xs tabular-nums text-muted">{fmtTs(v.duration)}</td>
                    <td className="px-2"><TypeBadge type={v.video_type} /></td>
                    <td className="px-2"><StatusBadge status={v.transcript_status} title={v.last_error ?? undefined} /></td>
                    <td className="px-2"><StatusBadge status={v.analysis_status} /></td>
                    <td className="px-2 tabular-nums">{v.idea_count || "–"}</td>
                    <td className="px-2"><a href={v.url} target="_blank" rel="noreferrer" aria-label="Open on YouTube" className="text-muted hover:text-fg"><ExternalLink className="size-4" /></a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
      {data && data.total > 0 && (
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{data.total.toLocaleString()} video(s){isFetching ? " · updating…" : ""}</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
            <span>Page {page} of {pages}</span>
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
          </div>
        </div>
      )}
    </div>
  );
}
