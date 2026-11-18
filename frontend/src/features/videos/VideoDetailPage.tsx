import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Download, ExternalLink, RefreshCw, Sparkles } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { StatusBadge, TypeBadge } from "@/components/ui/status";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useVideo, useVideoIdeas } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { fmtDate, fmtTs, label } from "@/lib/utils";
import { TranscriptReader } from "@/features/transcripts/TranscriptReader";
import { IdeaCard } from "@/features/ideas/IdeaCard";
import { JobRow, JOB_NAMES } from "@/features/processing/JobRow";

export function VideoDetailPage() {
  const { id = "" } = useParams();
  const [sp] = useSearchParams();
  const [tab, setTab] = useState(sp.get("seg") ? "transcript" : "ideas");
  const [focus, setFocus] = useState<string | null>(sp.get("seg"));
  const [typeFilter, setTypeFilter] = useState("");
  const { data: v, isLoading, error, refetch } = useVideo(id);
  const ideas = useVideoIdeas(id);
  const process = useAction((force: boolean) => api.post(`/api/videos/${id}/process`, undefined, { force }), "Transcript collection queued");
  const analyze = useAction(() => api.post(`/api/videos/${id}/analyze`), "Idea extraction queued");
  const exportV = useAction((format: string) => api.post("/api/exports", { scope: "video", ids: [id], format }), "Export queued — see Exports page");

  if (isLoading) return <Loading />;
  if (error || !v) return <div className="p-6"><ErrorState error={error ?? "Not found"} onRetry={refetch} /></div>;
  const a = v.analysis;
  const list = (ideas.data?.ideas ?? []).filter((i) => !typeFilter || i.idea_type === typeFilter);
  const types = [...new Set((ideas.data?.ideas ?? []).map((i) => i.idea_type))].sort();
  const showInTranscript = (k: string) => { setFocus(k); setTab("transcript"); };

  return (
    <div className="pb-8">
      <PageHeader title={v.title || v.id}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          {v.channel?.name ?? "Unknown channel"} · {fmtDate(v.upload_date)} · {fmtTs(v.duration)} <TypeBadge type={v.video_type} />
          <a href={v.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">YouTube <ExternalLink className="size-3" /></a>
        </span>}
        actions={<>
          <Button variant="secondary" onClick={() => process.mutate(v.transcript_status === "completed")}><RefreshCw />{v.transcript_status === "completed" ? "Re-fetch transcript" : "Collect transcript"}</Button>
          <Button onClick={() => analyze.mutate(undefined)} disabled={v.transcript_status !== "completed"}><Sparkles />{a ? "Re-analyse" : "Extract ideas"}</Button>
          <Select aria-label="Export format" defaultValue="" onChange={(e) => { if (e.target.value) exportV.mutate(e.target.value); e.target.value = ""; }}>
            <option value="" disabled>Export…</option>
            <option value="zip">ZIP archive</option><option value="json">JSON</option><option value="md">Markdown</option><option value="txt">Text</option><option value="csv">CSV (ideas)</option>
          </Select>
        </>} />
      <div className="grid gap-4 px-6 xl:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="ideas">Ideas ({v.idea_count})</TabsTrigger>
              <TabsTrigger value="summary">Summary</TabsTrigger>
              <TabsTrigger value="transcript">Transcript</TabsTrigger>
              <TabsTrigger value="history">Processing history</TabsTrigger>
            </TabsList>
            <TabsContent value="ideas" className="pt-4">
              {ideas.isLoading ? <Loading /> : !list.length && !typeFilter ? (
                <Card><Empty title="No ideas extracted yet">{v.transcript_status === "completed" ? "Run idea extraction (requires Ollama)." : "Collect the transcript first."}</Empty></Card>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <Select aria-label="Filter idea type" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                      <option value="">All types</option>{types.map((t) => <option key={t} value={t}>{label(t)}</option>)}
                    </Select>
                    <span className="text-xs text-muted">{list.length} idea(s)</span>
                  </div>
                  {list.map((i) => <IdeaCard key={i.id} idea={i} showSource={false} onShowInTranscript={showInTranscript} />)}
                </div>
              )}
            </TabsContent>
            <TabsContent value="summary" className="pt-4">
              {!a ? <Card><Empty title="No analysis yet" /></Card> : (
                <Card><CardContent className="space-y-4 text-sm leading-relaxed">
                  {a.main_theme && <section><h3 className="mb-1 font-semibold">Main theme</h3><p>{a.main_theme}</p></section>}
                  {a.central_thesis && <section><h3 className="mb-1 font-semibold">Central thesis</h3><p>{a.central_thesis}</p></section>}
                  {a.summary && <section><h3 className="mb-1 font-semibold">Detailed summary</h3><p className="whitespace-pre-wrap">{a.summary}</p></section>}
                  {a.takeaways.length > 0 && <section><h3 className="mb-1 font-semibold">Practical takeaways</h3><ul className="list-disc pl-5">{a.takeaways.map((t, i) => <li key={i}>{t}</li>)}</ul></section>}
                  {a.topics.length > 0 && <section><h3 className="mb-1 font-semibold">Topics</h3><div className="flex flex-wrap gap-1">{a.topics.map((t) => <Badge key={t}>{t}</Badge>)}</div></section>}
                  {a.relationships.length > 0 && ideas.data && (
                    <section><h3 className="mb-1 font-semibold">Concept relationships</h3>
                      <ul className="space-y-0.5 text-xs">{a.relationships.map((r, i) => {
                        const s = ideas.data!.ideas[r.source - 1]; const t = ideas.data!.ideas[r.target - 1];
                        return s && t ? <li key={i}>{s.title} <span className="text-accent">— {label(r.relation)} →</span> {t.title}</li> : null;
                      })}</ul></section>
                  )}
                  <section className="border-t border-border pt-3 text-xs text-muted">
                    Model <span className="font-mono">{a.model}</span> · analysis v{a.analysis_version} · prompts {Object.entries(a.prompt_versions).map(([k, n]) => `${k}@${n}`).join(", ")} ·
                    {" "}{a.chunk_count} chunk(s) · {a.raw_idea_count} raw → {v.idea_count} final ideas · {String(a.validation.dropped_unsourced ?? 0)} unsourced dropped · {String(a.validation.merged ?? 0)} merged
                  </section>
                </CardContent></Card>
              )}
            </TabsContent>
            <TabsContent value="transcript" className="pt-4">
              {v.transcripts.length ? <TranscriptReader videoId={id} transcripts={v.transcripts} focusKey={focus} /> :
                <Card><Empty title="No transcript yet">Status: {label(v.transcript_status)}{v.last_error ? ` — ${v.last_error}` : ""}</Empty></Card>}
            </TabsContent>
            <TabsContent value="history" className="pt-4">
              <Card className="divide-y divide-border">{v.jobs.length ? v.jobs.map((j) => <JobRow key={j.id} job={j} />) : <Empty title="No jobs yet" />}</Card>
            </TabsContent>
          </Tabs>
        </div>
        <div className="space-y-3">
          <Card>
            <CardHeader><CardTitle>Status</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-muted">Transcript</span><StatusBadge status={v.transcript_status} /></div>
              <div className="flex justify-between"><span className="text-muted">AI analysis</span><StatusBadge status={v.analysis_status} /></div>
              <div className="flex justify-between"><span className="text-muted">Availability</span><span>{v.availability}</span></div>
              <div className="flex justify-between"><span className="text-muted">Captions</span><span>{v.has_manual_subs ? "creator" : ""}{v.has_manual_subs && v.has_auto_subs ? " + " : ""}{v.has_auto_subs ? "auto" : ""}{v.has_manual_subs === false && v.has_auto_subs === false ? "none" : v.has_manual_subs == null ? "unknown" : ""}</span></div>
              {v.last_error && <div className="rounded bg-danger/10 p-2 text-xs text-danger">{v.last_error}</div>}
              {v.jobs.filter((j) => ["running", "queued", "retry_scheduled"].includes(j.status)).map((j) => (
                <div key={j.id} className="text-xs text-muted">{JOB_NAMES[j.job_type]}: {label(j.stage)}</div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Metadata</CardTitle></CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              <div><span className="text-muted">Video ID </span><span className="font-mono">{v.id}</span></div>
              <div><span className="text-muted">Language </span>{v.language ?? "–"}</div>
              <div><span className="text-muted">Listed in </span>{v.listing_sources.join(", ") || "–"} <span className="text-muted">(type from {v.type_source})</span></div>
              {v.view_count != null && <div><span className="text-muted">Views </span>{v.view_count.toLocaleString()}</div>}
              {v.description && <p className="mt-2 line-clamp-[12] whitespace-pre-wrap text-muted">{v.description}</p>}
            </CardContent>
          </Card>
          {v.orphaned_annotations.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Notes from earlier analyses</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-xs">
                {v.orphaned_annotations.map((o) => <div key={o.id}><div className="font-medium">{o.idea_title}</div>{o.note && <div className="text-muted">{o.note}</div>}</div>)}
              </CardContent>
            </Card>
          )}
          <Button variant="secondary" className="w-full" asChild>
            <a href={api.url(`/api/videos/${id}/summary.md`)} target="_blank" rel="noreferrer"><Download />summary.md</a>
          </Button>
        </div>
      </div>
    </div>
  );
}
