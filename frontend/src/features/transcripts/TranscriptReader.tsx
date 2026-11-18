import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Copy, Download, ExternalLink } from "lucide-react";
import type { Transcript, TranscriptInfo } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Badge, Input, Select } from "@/components/ui/primitives";
import { MethodBadge } from "@/components/ui/status";
import { ErrorState, Loading } from "@/components/ui/states";
import { useTranscript } from "@/hooks/queries";
import { useUI } from "@/stores/ui";
import { api } from "@/services/api";
import { cn, fmtTs } from "@/lib/utils";

function Highlight({ text, term }: { text: string; term: string }) {
  if (!term) return <>{text}</>;
  const parts = text.split(new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return <>{parts.map((p, i) => (p.toLowerCase() === term.toLowerCase() ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>))}</>;
}

export function TranscriptView({ transcript, focusKey, height = 560 }: { transcript: Transcript; focusKey?: string | null; height?: number }) {
  const [mode, setMode] = useState<"timestamped" | "plain">("timestamped");
  const [term, setTerm] = useState("");
  const [matchIdx, setMatchIdx] = useState(0);
  const toast = useUI((s) => s.toast);
  const parentRef = useRef<HTMLDivElement>(null);
  const segs = transcript.segments;
  const matches = useMemo(() => (term.length < 2 ? [] : segs.map((s, i) => (s.text.toLowerCase().includes(term.toLowerCase()) ? i : -1)).filter((i) => i >= 0)), [segs, term]);
  const v = useVirtualizer({ count: segs.length, getScrollElement: () => parentRef.current, estimateSize: () => 44, overscan: 12, initialRect: { width: 800, height: 560 } });

  useEffect(() => {
    if (!focusKey) return;
    const idx = segs.findIndex((s) => s.id === focusKey);
    if (idx >= 0) v.scrollToIndex(idx, { align: "center" });
  }, [focusKey, segs, v]);
  useEffect(() => {
    if (matches.length) v.scrollToIndex(matches[matchIdx % matches.length], { align: "center" });
  }, [matchIdx, matches, v]);

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(transcript.segments.map((s) => s.text).join("\n"));
      toast("Transcript copied", "success");
    } catch {
      toast("Clipboard unavailable — select text and copy manually", "error");
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <MethodBadge method={transcript.method} />
        <Badge tone={transcript.completeness === "complete" ? "ok" : transcript.completeness === "partial" ? "warn" : "muted"}
          title={transcript.coverage_ratio != null ? `Timestamp coverage ${Math.round(transcript.coverage_ratio * 100)}%` : undefined}>
          {transcript.completeness}
        </Badge>
        {transcript.language && <Badge tone="muted">{transcript.language}</Badge>}
        <span className="text-xs text-muted">{transcript.word_count.toLocaleString()} words · {transcript.segment_count} segments</span>
        <div className="ml-auto flex items-center gap-1">
          <Input aria-label="Search transcript" placeholder="Find in transcript…" className="w-48" value={term} onChange={(e) => { setTerm(e.target.value); setMatchIdx(0); }}
            onKeyDown={(e) => e.key === "Enter" && setMatchIdx((i) => i + 1)} />
          {term.length >= 2 && <span className="w-16 text-xs text-muted">{matches.length ? `${(matchIdx % matches.length) + 1}/${matches.length}` : "0 hits"}</span>}
          <Select aria-label="View mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="timestamped">Timestamped</option><option value="plain">Plain text</option>
          </Select>
          <Button size="sm" variant="ghost" onClick={copyAll} title="Copy all" aria-label="Copy transcript"><Copy /></Button>
          <Button size="sm" variant="ghost" asChild title="Download">
            <a href={api.url(`/api/videos/${transcript.video_id}/transcript/download`, { format: mode === "plain" ? "txt" : "timestamped", transcript_id: transcript.id })} aria-label="Download transcript"><Download /></a>
          </Button>
        </div>
      </div>
      {transcript.completeness !== "complete" && (
        <div className="rounded border border-warn/30 bg-warn/10 px-3 py-1.5 text-xs">
          This transcript may be incomplete. It contains only the speech that was captured; nothing has been filled in.
        </div>
      )}
      {mode === "plain" ? (
        <div className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-md border border-border bg-panel-2 p-4 leading-relaxed select-text">
          <Highlight text={segs.map((s) => s.text).join(" ")} term={term.length >= 2 ? term : ""} />
        </div>
      ) : (
        <div ref={parentRef} style={{ height }} className="overflow-auto rounded-md border border-border bg-panel-2 select-text" data-testid="transcript-scroll">
          <div style={{ height: v.getTotalSize(), position: "relative" }}>
            {v.getVirtualItems().map((item) => {
              const s = segs[item.index];
              const focused = s.id === focusKey;
              return (
                <div key={s.id} data-index={item.index} ref={v.measureElement}
                  className={cn("absolute left-0 top-0 flex w-full gap-3 px-3 py-1.5", focused && "bg-accent/15")}
                  style={{ transform: `translateY(${item.start}px)` }}>
                  <a href={s.url} target="_blank" rel="noreferrer" className="w-14 shrink-0 pt-px font-mono text-xs text-accent hover:underline" title={`Open at ${fmtTs(s.start)} on YouTube`}>
                    {fmtTs(s.start)}
                  </a>
                  <span className="leading-relaxed"><Highlight text={s.text} term={term.length >= 2 ? term : ""} /></span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function TranscriptReader({ videoId, transcripts, focusKey }: { videoId: string; transcripts: TranscriptInfo[]; focusKey?: string | null }) {
  const current = transcripts.find((t) => t.is_current && t.kind === "source") ?? transcripts[0];
  const [chosen, setChosen] = useState<number | undefined>(current?.id);
  const { data, isLoading, error } = useTranscript(videoId, chosen, !!current);
  if (!current) return null;
  return (
    <div className="space-y-2">
      {transcripts.length > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted">Version</span>
          <Select aria-label="Transcript version" value={chosen} onChange={(e) => setChosen(Number(e.target.value))}>
            {transcripts.map((t) => (
              <option key={t.id} value={t.id}>{t.kind === "source" ? "Original" : "Derived"} · {t.method} · {new Date(t.created_at + "Z").toLocaleDateString()}{t.is_current ? " (current)" : ""}</option>
            ))}
          </Select>
          {current.has_raw_caption && <a className="inline-flex items-center gap-1 text-accent" href={api.url(`/api/videos/${videoId}/transcript/download`, { format: "original", transcript_id: chosen })}>Original caption file <ExternalLink className="size-3" /></a>}
        </div>
      )}
      {isLoading ? <Loading /> : error ? <ErrorState error={error} /> : data ? <TranscriptView transcript={data} focusKey={focusKey} /> : null}
    </div>
  );
}
