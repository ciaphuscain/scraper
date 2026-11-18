import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Download, X } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Select } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { useChannels } from "@/hooks/queries";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/services/api";
import { useIdeaSelection, useUI } from "@/stores/ui";
import type { Idea, Paged } from "@/types/api";
import { label } from "@/lib/utils";
import { IdeaCard } from "./IdeaCard";

type Facets = { topics: { value: string; count: number }[]; idea_types: { value: string; count: number }[]; tags: { value: string; count: number }[] };

export function IdeasPage() {
  const [f, setF] = useState({ q: "", channel_id: "", topic: "", idea_type: "", video_type: "", statement_kind: "", date_from: "", date_to: "", tag: "", sort: "newest" });
  const [bookmarked, setBookmarked] = useState(false);
  const q = useDebounced(f.q);
  const params = { ...f, q, bookmarked: bookmarked || undefined, sort: q && f.sort === "newest" ? "relevance" : f.sort };
  const channels = useChannels();
  const facets = useQuery({ queryKey: ["facets", f.channel_id], queryFn: () => api.get<Facets>("/api/ideas/facets", { channel_id: f.channel_id }) });
  const pageSize = 50;
  const query = useInfiniteQuery({
    queryKey: ["ideasInfinite", params],
    queryFn: ({ pageParam }) => api.get<Paged<"ideas", Idea>>("/api/ideas", { ...params, page: pageParam, page_size: pageSize }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
  });
  const ideas = useMemo(() => query.data?.pages.flatMap((p) => p.ideas) ?? [], [query.data]);
  const total = query.data?.pages[0]?.total ?? 0;
  const parentRef = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: ideas.length, getScrollElement: () => parentRef.current, estimateSize: () => 220, overscan: 6, initialRect: { width: 1000, height: 800 } });
  const items = v.getVirtualItems();
  const last = items[items.length - 1];
  const nearEnd = !!last && last.index >= ideas.length - 5;
  useEffect(() => {
    if (nearEnd && query.hasNextPage && !query.isFetchingNextPage) query.fetchNextPage();
  }, [nearEnd, query]);

  const sel = useIdeaSelection();
  const toast = useUI((s) => s.toast);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const doExport = async (format: string) => {
    try {
      const res = await fetch(api.url("/api/ideas/export"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: sel.ideaIds, format }) });
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `ideas_export.${format}`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Idea explorer" subtitle={`${total.toLocaleString()} idea(s)`} />
      <div className="flex flex-wrap items-center gap-2 px-6 pb-3">
        <Input aria-label="Search ideas" placeholder="Search ideas, explanations, keywords…" className="w-72" value={f.q} onChange={set("q")} />
        <Select aria-label="Channel" value={f.channel_id} onChange={set("channel_id")}>
          <option value="">All channels</option>{channels.data?.channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Select aria-label="Topic" value={f.topic} onChange={set("topic")} className="max-w-48">
          <option value="">All topics</option>{facets.data?.topics.map((t) => <option key={t.value} value={t.value}>{t.value} ({t.count})</option>)}
        </Select>
        <Select aria-label="Idea type" value={f.idea_type} onChange={set("idea_type")}>
          <option value="">All idea types</option>{facets.data?.idea_types.map((t) => <option key={t.value} value={t.value}>{label(t.value)} ({t.count})</option>)}
        </Select>
        <Select aria-label="Content type" value={f.video_type} onChange={set("video_type")}>
          <option value="">Videos & Shorts</option><option value="video">Videos</option><option value="short">Shorts</option>
        </Select>
        <Select aria-label="Statement kind" value={f.statement_kind} onChange={set("statement_kind")}>
          <option value="">Any statement</option><option value="stated">Directly stated</option><option value="creator_claim">Creator claims</option><option value="interpretation">Interpretations</option>
        </Select>
        {facets.data?.tags.length ? (
          <Select aria-label="Tag" value={f.tag} onChange={set("tag")}>
            <option value="">Any tag</option>{facets.data.tags.map((t) => <option key={t.value} value={t.value}>{t.value}</option>)}
          </Select>
        ) : null}
        <Input aria-label="From" type="date" className="w-36" value={f.date_from} onChange={set("date_from")} />
        <Input aria-label="To" type="date" className="w-36" value={f.date_to} onChange={set("date_to")} />
        <label className="flex items-center gap-1.5 text-sm"><Checkbox checked={bookmarked} onChange={(e) => setBookmarked(e.target.checked)} />Bookmarked</label>
        <Select aria-label="Sort" value={f.sort} onChange={set("sort")}>
          <option value="newest">Newest</option><option value="oldest">Oldest</option><option value="relevance">Relevance</option><option value="confidence">Confidence</option><option value="title">Title</option>
        </Select>
      </div>
      {sel.ideaIds.length > 0 && (
        <div className="mx-6 mb-3 flex items-center gap-2 rounded-md border border-accent/30 bg-accent/10 px-3 py-2 text-sm">
          <span className="font-medium">{sel.ideaIds.length} selected</span>
          <Button size="sm" onClick={() => doExport("json")}><Download />JSON</Button>
          <Button size="sm" variant="secondary" onClick={() => doExport("csv")}>CSV</Button>
          <Button size="sm" variant="secondary" onClick={() => doExport("md")}>Markdown</Button>
          <Button size="sm" variant="secondary" onClick={() => sel.set([...new Set([...sel.ideaIds, ...ideas.map((i) => i.id)])])}>Select all loaded</Button>
          <Button size="sm" variant="ghost" onClick={sel.clear}><X />Clear</Button>
        </div>
      )}
      <div className="min-h-0 flex-1 px-6 pb-4">
        {query.isLoading ? <Loading /> : query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : !ideas.length ? (
          <Empty title="No ideas found">Ideas appear after transcripts are analysed with Ollama.</Empty>
        ) : (
          <div ref={parentRef} className="h-full overflow-auto" data-testid="ideas-scroll">
            <div style={{ height: v.getTotalSize(), position: "relative" }}>
              {items.map((item) => {
                const idea = ideas[item.index];
                return (
                  <div key={idea.id} data-index={item.index} ref={v.measureElement} className="absolute left-0 top-0 w-full pb-3" style={{ transform: `translateY(${item.start}px)` }}>
                    <IdeaCard idea={idea} selected={sel.ideaIds.includes(idea.id)} onSelect={() => sel.toggle(idea.id)} />
                  </div>
                );
              })}
            </div>
            {query.isFetchingNextPage && <Loading label="Loading more…" />}
          </div>
        )}
      </div>
    </div>
  );
}
