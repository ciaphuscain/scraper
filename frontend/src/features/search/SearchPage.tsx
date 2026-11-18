import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Badge, Card, Input, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { useChannels } from "@/hooks/queries";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/services/api";
import type { SearchResult } from "@/types/api";
import { cn, fmtDate, fmtTs, snippetParts } from "@/lib/utils";

const KIND_LABEL: Record<string, string> = { ideas: "Idea", segments: "Transcript", videos: "Video", channels: "Channel" };

function Snippet({ text }: { text: string }) {
  return <>{snippetParts(text).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}</>;
}

function ResultItem({ r }: { r: SearchResult }) {
  const to = r.kind === "channels" ? `/channels/${r.channel_id}` : r.kind === "segments" ? `/videos/${r.video_id}?seg=${r.seg_key}` : `/videos/${r.video_id}`;
  return (
    <li className="px-4 py-3 hover:bg-panel-2/50">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Badge tone={r.kind === "ideas" ? "accent" : "default"}>{KIND_LABEL[r.kind]}</Badge>
        {r.channel_name && <span>{r.channel_name}</span>}
        {r.upload_date && <span>· {fmtDate(r.upload_date)}</span>}
        {r.video_type === "short" && <Badge tone="accent">Short</Badge>}
        {r.topic && <span>· {r.topic}</span>}
      </div>
      <Link to={to} className="mt-1 block font-medium hover:text-accent">{r.kind === "segments" ? r.video_title : r.title ?? r.video_title}</Link>
      <p className="mt-0.5 text-sm text-fg/80"><Snippet text={r.snippet ?? ""} /></p>
      {r.url && r.start != null && (
        <a href={r.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline"><ExternalLink className="size-3" />{fmtTs(r.start)}</a>
      )}
    </li>
  );
}

export function SearchPage() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [kinds, setKinds] = useState("");
  const [channel, setChannel] = useState("");
  const [vtype, setVtype] = useState("");
  const [sort, setSort] = useState("relevance");
  const dq = useDebounced(q, 350);
  const channels = useChannels();
  const res = useQuery({
    queryKey: ["search", dq, kinds, channel, vtype, sort],
    queryFn: () => api.get<{ results: SearchResult[]; counts: Record<string, number> }>("/api/search", { q: dq, kinds, channel_id: channel, video_type: vtype, sort, limit: 50 }),
    enabled: dq.trim().length > 0,
  });
  return (
    <div className="pb-8">
      <PageHeader title="Search" subtitle={'Full-text search across titles, descriptions, transcripts, ideas and channels. Use "quotes" for phrases, word* for prefixes, OR for alternatives.'} />
      <div className="space-y-3 px-6">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <Input autoFocus aria-label="Search query" className="h-10 pl-9 text-base" placeholder="Search everything…" value={q}
            onChange={(e) => { setQ(e.target.value); setSp(e.target.value ? { q: e.target.value } : {}, { replace: true }); }} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["", "ideas", "segments", "videos", "channels"] as const).map((k) => (
            <button key={k} onClick={() => setKinds(k)} className={cn("rounded-full border px-3 py-1 text-xs", kinds === k ? "border-accent bg-accent/15 text-accent" : "border-border text-muted hover:text-fg")}>
              {k ? KIND_LABEL[k] + "s" : "All"}{k && res.data?.counts[k] != null ? ` (${res.data.counts[k]})` : ""}
            </button>
          ))}
          <Select aria-label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">All channels</option>{channels.data?.channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          <Select aria-label="Type" value={vtype} onChange={(e) => setVtype(e.target.value)}>
            <option value="">Videos & Shorts</option><option value="video">Videos</option><option value="short">Shorts</option>
          </Select>
          <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="relevance">Relevance</option><option value="newest">Newest</option><option value="oldest">Oldest</option>
          </Select>
        </div>
        {!dq.trim() ? <Empty title="Type to search" icon={<Search className="size-8" />} /> : res.isLoading ? <Loading /> : res.error ? <ErrorState error={res.error} /> : (
          <Card>
            {res.data?.results.length ? <ul className="divide-y divide-border">{res.data.results.map((r, i) => <ResultItem key={`${r.kind}-${i}`} r={r} />)}</ul> : <Empty title="No results" />}
          </Card>
        )}
      </div>
    </div>
  );
}
