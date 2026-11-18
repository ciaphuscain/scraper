import { useState } from "react";
import { Link } from "react-router-dom";
import { Bookmark, BookmarkCheck, ExternalLink, FileText, StickyNote, Tag } from "lucide-react";
import type { Idea } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Badge, Card, Checkbox, Input, Textarea } from "@/components/ui/primitives";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import { cn, fmtDate, fmtTs, label } from "@/lib/utils";

const kindTone: Record<string, string> = { stated: "ok", creator_claim: "warn", interpretation: "accent", verified_fact: "ok" };
const kindLabel: Record<string, string> = { stated: "Directly stated", creator_claim: "Creator claim (unverified)", interpretation: "Interpretation", verified_fact: "Verified" };

export function IdeaCard({ idea, showSource = true, onShowInTranscript, selected, onSelect }: {
  idea: Idea; showSource?: boolean; onShowInTranscript?: (segKey: string) => void; selected?: boolean; onSelect?: () => void;
}) {
  const ann = idea.annotation;
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(ann?.note ?? "");
  const [tags, setTags] = useState((ann?.tags ?? []).join(", "));
  const save = useAction((body: Record<string, unknown>) => api.put(`/api/ideas/${idea.id}/annotation`, body));
  const toggleBookmark = () => save.mutate({ bookmarked: !ann?.bookmarked });
  const saveNote = () => save.mutate({ note, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }, { onSuccess: () => setEditing(false) });

  return (
    <Card className={cn("p-4", selected && "border-accent")}>
      <div className="flex items-start gap-3">
        {onSelect && <Checkbox aria-label={`Select idea ${idea.title}`} checked={!!selected} onChange={onSelect} className="mt-1" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="accent">{label(idea.idea_type)}</Badge>
            {idea.topic && <Badge>{idea.topic}</Badge>}
            <Badge tone={kindTone[idea.statement_kind] ?? "default"}>{kindLabel[idea.statement_kind] ?? idea.statement_kind}</Badge>
            {idea.confidence != null && <span className="text-[11px] text-muted">confidence {Math.round(idea.confidence * 100)}%</span>}
          </div>
          <h3 className="mt-1.5 font-semibold leading-snug">{idea.title}</h3>
          <p className="mt-1 text-sm leading-relaxed text-fg/85">{idea.explanation}</p>
          {idea.excerpts.length > 0 && (
            <div className="mt-2 space-y-1">
              {idea.excerpts.slice(0, 3).map((ex, i) => (
                <blockquote key={i} className="border-l-2 border-accent/50 pl-2.5 text-sm italic text-muted">
                  “{ex.text}”
                  <a href={`https://www.youtube.com/watch?v=${idea.video_id}&t=${Math.floor(ex.start)}s`} target="_blank" rel="noreferrer" className="ml-1.5 not-italic text-accent hover:underline">{fmtTs(ex.start)}</a>
                </blockquote>
              ))}
            </div>
          )}
          {idea.keywords.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{idea.keywords.map((k) => <span key={k} className="rounded bg-panel-2 px-1.5 py-0.5 text-[11px] text-muted">{k}</span>)}</div>}
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {showSource && (
              <Link to={`/videos/${idea.video_id}?seg=${idea.segment_ids[0] ?? ""}`} className="max-w-xs truncate hover:text-fg">
                {idea.video_title ?? idea.video_id}
              </Link>
            )}
            {showSource && idea.channel_name && <span>{idea.channel_name}</span>}
            {idea.upload_date && <span>{fmtDate(idea.upload_date)}</span>}
            <a href={idea.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
              <ExternalLink className="size-3" />{fmtTs(idea.start_time)}{idea.end_time != null ? `–${fmtTs(idea.end_time)}` : ""}
            </a>
            {onShowInTranscript && idea.segment_ids[0] && (
              <button className="inline-flex items-center gap-1 hover:text-fg" onClick={() => onShowInTranscript(idea.segment_ids[0])}><FileText className="size-3" />Show in transcript</button>
            )}
            <span title={`Segments ${idea.segment_ids.join(", ")}`}>{idea.segment_ids.length} source segment(s)</span>
          </div>
          {ann && (ann.note || ann.tags.length > 0) && !editing && (
            <div className="mt-2 rounded border border-border bg-panel-2 p-2 text-sm">
              {ann.note && <div className="whitespace-pre-wrap">{ann.note}</div>}
              {ann.tags.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{ann.tags.map((t) => <Badge key={t} tone="muted"><Tag className="size-3" />{t}</Badge>)}</div>}
            </div>
          )}
          {editing && (
            <div className="mt-2 space-y-2">
              <Textarea aria-label="Personal note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Your note (kept separate from AI output)" />
              <Input aria-label="Tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="tags, comma separated" />
              <div className="flex gap-2"><Button size="sm" onClick={saveNote}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button></div>
            </div>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <Button size="icon" variant="ghost" aria-label={ann?.bookmarked ? "Remove bookmark" : "Bookmark"} onClick={toggleBookmark}>
            {ann?.bookmarked ? <BookmarkCheck className="text-accent" /> : <Bookmark />}
          </Button>
          <Button size="icon" variant="ghost" aria-label="Edit note and tags" onClick={() => setEditing(!editing)}><StickyNote /></Button>
        </div>
      </div>
    </Card>
  );
}
