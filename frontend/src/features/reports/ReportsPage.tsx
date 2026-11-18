import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, ExternalLink, GitCompare } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Checkbox, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useChannels } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { fmtDate, fmtTs } from "@/lib/utils";

type Ref = { idea_id: number; title: string; video_id: string; video_title?: string; start: number | null; url: string; channel_name?: string };

function RefLink({ r }: { r: Ref }) {
  return (
    <a href={r.url} target="_blank" rel="noreferrer" className="group inline-flex items-baseline gap-1 hover:text-accent">
      <span>{r.title}</span>
      <span className="text-xs text-muted group-hover:text-accent">({r.video_title ?? r.video_id} @ {fmtTs(r.start)}) <ExternalLink className="inline size-3" /></span>
    </a>
  );
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function ChannelReportView({ channelId }: { channelId: string }) {
  const rep = useQuery({ queryKey: ["report", channelId], queryFn: () => api.get<{ report: any }>(`/api/reports/channels/${channelId}`), refetchInterval: 5000 });
  const gen = useAction((useLlm: boolean) => api.post(`/api/reports/channels/${channelId}`, undefined, { use_llm: useLlm }), "Report generation queued");
  if (rep.isLoading) return <Loading />;
  if (rep.error) return <ErrorState error={rep.error} />;
  const r = rep.data?.report;
  const header = (
    <div className="flex items-center gap-2">
      <Button onClick={() => gen.mutate(true)}><BarChart3 />Generate report</Button>
      <Button variant="secondary" onClick={() => gen.mutate(false)}>Generate without LLM</Button>
      {r && <span className="text-xs text-muted">Last generated {fmtDate(r.created_at)}{r.model ? ` · narrative by ${r.model}` : " · no LLM narrative"}</span>}
    </div>
  );
  if (!r) return <div className="space-y-3">{header}<Card><Empty title="No report yet">Reports aggregate extracted ideas; analyse some videos first.</Empty></Card></div>;
  const d = r.data;
  const n = r.narrative;
  return (
    <div className="space-y-4">
      {header}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {Object.entries(d.totals).map(([k, v]) => <Card key={k} className="p-3"><div className="text-xs capitalize text-muted">{k}</div><div className="text-xl font-semibold">{String(v)}</div></Card>)}
      </div>
      {n && (
        <Card><CardHeader><CardTitle>Overview (LLM, citation-checked)</CardTitle>{n.dropped_uncited > 0 && <Badge tone="warn">{n.dropped_uncited} uncited statement(s) removed</Badge>}</CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>{n.overview}</p>
            {["recurring_themes", "notable_insights", "evolution"].map((k) => n[k]?.length ? (
              <div key={k}><div className="mb-1 font-medium capitalize">{k.replace("_", " ")}</div>
                <ul className="list-disc space-y-1 pl-5">{n[k].map((s: any, i: number) => <li key={i}>{s.statement} <span className="text-xs text-muted">[ideas {s.idea_ids.join(", ")}]</span></li>)}</ul></div>
            ) : null)}
          </CardContent></Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card><CardHeader><CardTitle>Topic distribution</CardTitle></CardHeader>
          <CardContent className="space-y-1.5">
            {d.topic_distribution.slice(0, 20).map((t: any) => {
              const max = d.topic_distribution[0]?.ideas || 1;
              return (
                <div key={t.topic} className="text-sm">
                  <div className="flex justify-between"><span>{t.topic}</span><span className="text-xs text-muted">{t.ideas} ideas · {t.videos} videos</span></div>
                  <div className="h-1.5 rounded bg-panel-2"><div className="h-full rounded bg-accent" style={{ width: `${(t.ideas / max) * 100}%` }} /></div>
                </div>
              );
            })}
          </CardContent></Card>
        <Card><CardHeader><CardTitle>Recurring themes</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {d.recurring_themes.length ? d.recurring_themes.slice(0, 12).map((t: any) => (
              <div key={t.topic}><div className="font-medium">{t.topic} <span className="text-xs text-muted">in {t.video_count} uploads</span></div>
                <ul className="mt-0.5 space-y-0.5 pl-3">{t.sources.slice(0, 3).map((s: Ref) => <li key={s.idea_id}><RefLink r={s} /></li>)}</ul></div>
            )) : <div className="text-muted">No topic spans multiple uploads yet.</div>}
          </CardContent></Card>
        <Card><CardHeader><CardTitle>Frequently discussed concepts</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">{d.frequent_concepts.slice(0, 50).map((c: any) => <Badge key={c.concept} title={`${c.video_count} uploads`}>{c.concept} · {c.video_count}</Badge>)}</CardContent></Card>
        <Card><CardHeader><CardTitle>Videos vs Shorts</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">{Object.entries(d.video_vs_shorts).map(([k, v]: [string, any]) => (
            <div key={k}><div className="font-medium"><span className="capitalize">{k}s</span>: {v.videos} · {v.analysed} analysed · {v.ideas} ideas · {v.avg_ideas_per_analysed ?? "–"} ideas/upload</div>
              <div className="text-xs text-muted">{v.top_topics.map(([t, c]: [string, number]) => `${t} (${c})`).join(", ")}</div></div>
          ))}</CardContent></Card>
        <Card><CardHeader><CardTitle>Topic emphasis over time</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">{d.emphasis_over_time.map((e: any) => (
            <div key={e.period}><span className="font-medium">{e.period}</span> <span className="text-muted">({e.ideas})</span>: {e.top_topics.slice(0, 5).map(([t, c]: [string, number]) => `${t} ${c}`).join(", ")}</div>
          ))}</CardContent></Card>
        <Card><CardHeader><CardTitle>Unique ideas</CardTitle></CardHeader>
          <CardContent><ul className="space-y-1 text-sm">{d.unique_ideas.slice(0, 15).map((u: Ref) => <li key={u.idea_id}><RefLink r={u} /></li>)}</ul></CardContent></Card>
        <Card><CardHeader><CardTitle>Important examples</CardTitle></CardHeader>
          <CardContent><ul className="space-y-1 text-sm">{d.important_examples.slice(0, 15).map((u: Ref) => <li key={u.idea_id}><RefLink r={u} /></li>)}</ul></CardContent></Card>
        <Card><CardHeader><CardTitle>Related ideas across uploads</CardTitle><Badge tone="muted">lexical candidates</Badge></CardHeader>
          <CardContent><ul className="space-y-2 text-sm">{d.related_across_uploads.slice(0, 15).map((p: any, i: number) => (
            <li key={i}><RefLink r={p.a} /> <span className="text-muted">↔</span> <RefLink r={p.b} /></li>
          ))}</ul></CardContent></Card>
      </div>
      <Card><CardHeader><CardTitle>Categorised idea index</CardTitle></CardHeader>
        <CardContent className="max-h-[480px] space-y-3 overflow-auto text-sm">{Object.entries(d.idea_index).map(([topic, items]: [string, any]) => (
          <div key={topic}><div className="font-medium">{topic} <span className="text-xs text-muted">({items.length})</span></div>
            <ul className="pl-3 text-muted">{items.map((x: any) => <li key={x.idea_id}><a className="hover:text-accent" href={`/videos/${x.video_id}`}>{x.title}</a> <span className="text-xs">@ {fmtTs(x.start)}</span></li>)}</ul></div>
        ))}</CardContent></Card>
    </div>
  );
}

function CrossChannel() {
  const channels = useChannels();
  const [sel, setSel] = useState<string[]>([]);
  const [validate, setValidate] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const list = useQuery({ queryKey: ["cross"], queryFn: () => api.get<{ reports: any[] }>("/api/reports/cross-channel"), refetchInterval: 5000 });
  const detail = useQuery({ queryKey: ["cross", open], queryFn: () => api.get<any>(`/api/reports/cross-channel/${open}`), enabled: open != null });
  const gen = useAction(() => api.post("/api/reports/cross-channel", { channel_ids: sel, validate_semantics: validate }), "Comparison queued");
  const d = detail.data?.data;
  const names: Record<string, string> = Object.fromEntries((d?.channels ?? []).map((c: any) => [c.id, c.name]));
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="mb-2 text-sm font-medium">Select channels to compare</div>
        <div className="flex flex-wrap gap-3">
          {channels.data?.channels.map((c) => (
            <label key={c.id} className="flex items-center gap-1.5 text-sm">
              <Checkbox checked={sel.includes(c.id)} onChange={() => setSel(sel.includes(c.id) ? sel.filter((x) => x !== c.id) : [...sel, c.id])} />{c.name} <span className="text-xs text-muted">({c.ideas})</span>
            </label>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button disabled={sel.length < 2} onClick={() => gen.mutate(undefined)}><GitCompare />Compare {sel.length} channels</Button>
          <label className="flex items-center gap-1.5 text-sm"><Checkbox checked={validate} onChange={(e) => setValidate(e.target.checked)} />Validate meaning with Ollama</label>
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <Card className="divide-y divide-border self-start">
          {list.data?.reports.length ? list.data.reports.map((r) => (
            <button key={r.id} onClick={() => setOpen(r.id)} className={`block w-full px-3 py-2 text-left text-sm hover:bg-panel-2 ${open === r.id ? "bg-panel-2" : ""}`}>
              {r.channels.map((c: any) => c.name).join(" vs ")}
              <div className="text-xs text-muted">{fmtDate(r.created_at)} {r.semantic_validation ? "· validated" : "· lexical only"}</div>
            </button>
          )) : <Empty title="No comparisons yet" />}
        </Card>
        <div>
          {open == null ? null : detail.isLoading ? <Loading /> : d && (
            <div className="space-y-4">
              {!d.semantic_validation && <div className="rounded border border-warn/30 bg-warn/10 p-2 text-xs">Not semantically validated: pairs are lexical candidates only.</div>}
              <Card><CardHeader><CardTitle>Shared topics</CardTitle></CardHeader>
                <CardContent className="space-y-1 text-sm">{d.shared_topics.slice(0, 25).map((s: any) => (
                  <div key={s.topic}><span className="font-medium">{s.topic}</span>: {Object.entries(s.channels).map(([c, n]) => `${names[c]} (${n})`).join(", ")}</div>
                ))}{!d.shared_topics.length && <span className="text-muted">None</span>}</CardContent></Card>
              {[["similar_ideas", "Similar ideas"], ["different_perspectives", "Different perspectives"], ["contradictory_claims", "Contradictory claims"],
                ["repeated_claims", "Repeated claims"], ["overlapping_examples", "Overlapping examples"], ["unvalidated_candidates", "Unvalidated candidates"]].map(([k, t]) => d[k]?.length ? (
                <Card key={k}><CardHeader><CardTitle>{t}</CardTitle><Badge>{d[k].length}</Badge></CardHeader>
                  <CardContent><ul className="space-y-2 text-sm">{d[k].map((e: any, i: number) => (
                    <li key={i}><div><RefLink r={e.a} /> <span className="text-xs text-muted">— {e.a.channel_name}</span></div>
                      <div><RefLink r={e.b} /> <span className="text-xs text-muted">— {e.b.channel_name}</span></div>
                      {e.explanation && <div className="text-xs text-muted">{e.explanation}</div>}</li>
                  ))}</ul></CardContent></Card>
              ) : null)}
              <Card><CardHeader><CardTitle>Topic frequency & unique concepts</CardTitle></CardHeader>
                <CardContent className="grid gap-4 text-sm md:grid-cols-2">{Object.keys(d.topic_frequency).map((cid) => (
                  <div key={cid}><div className="font-medium">{names[cid]}</div>
                    <div className="text-xs text-muted">{d.topic_frequency[cid].slice(0, 10).map(([t, n]: [string, number]) => `${t} (${n})`).join(", ")}</div>
                    <div className="mt-1 text-xs"><span className="text-muted">Unique topics:</span> {d.unique_topics[cid].slice(0, 10).join(", ") || "–"}</div>
                    <div className="text-xs"><span className="text-muted">Unique concepts:</span> {d.unique_concepts[cid].slice(0, 10).join(", ") || "–"}</div></div>
                ))}</CardContent></Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ReportsPage() {
  const [sp] = useSearchParams();
  const channels = useChannels();
  const [ch, setCh] = useState(sp.get("channel") ?? "");
  const current = ch || channels.data?.channels[0]?.id || "";
  return (
    <div className="pb-8">
      <PageHeader title="Reports" subtitle="Channel-level analysis and cross-channel comparison. Every finding links to its source video and timestamp." />
      <div className="px-6">
        <Tabs defaultValue="channel">
          <TabsList><TabsTrigger value="channel">Channel report</TabsTrigger><TabsTrigger value="cross">Cross-channel</TabsTrigger></TabsList>
          <TabsContent value="channel" className="space-y-4 pt-4">
            {channels.data?.channels.length ? <>
              <Select aria-label="Channel" value={current} onChange={(e) => setCh(e.target.value)}>
                {channels.data.channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
              {current && <ChannelReportView channelId={current} />}
            </> : <Empty title="Add a channel first" />}
          </TabsContent>
          <TabsContent value="cross" className="pt-4"><CrossChannel /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
