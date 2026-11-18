import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { StatusBadge } from "@/components/ui/status";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";
import type { ExportRecord } from "@/types/api";
import { fmtBytes, fmtDate } from "@/lib/utils";
import { ExportForm, type ExportSpec } from "./ExportForm";

export function ExportsPage() {
  const list = useQuery({ queryKey: ["exports"], queryFn: () => api.get<{ exports: ExportRecord[] }>("/api/exports"), refetchInterval: 3000 });
  const create = useAction((s: ExportSpec) => api.post("/api/exports", s), "Export queued");
  return (
    <div className="pb-8">
      <PageHeader title="Exports" subtitle="Portable exports of transcripts, ideas and metadata with original attribution. Single-video exports are available from each video page." />
      <div className="space-y-4 px-6">
        <ExportForm onSubmit={(s) => create.mutate(s)} busy={create.isPending} />
        {list.isLoading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : (
          <Card className="divide-y divide-border">
            {list.data?.exports.length ? list.data.exports.map((e) => (
              <div key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="font-medium uppercase">{e.format}</span><StatusBadge status={e.status} /><span className="text-xs text-muted">{e.scope}{e.target_ids.length ? ` (${e.target_ids.length})` : ""} · {e.content.join(", ")}</span></div>
                  <div className="text-xs text-muted">{fmtDate(e.created_at)} {e.file_name && `· ${e.file_name}`} {e.item_count != null && `· ${e.item_count} record(s)`} · {fmtBytes(e.size_bytes)}</div>
                  {e.error && <div className="text-xs text-danger">{e.error}</div>}
                </div>
                {e.status === "completed" && <Button size="sm" variant="secondary" asChild><a href={api.url(`/api/exports/${e.id}/download`)}><Download />Download</a></Button>}
              </div>
            )) : <Empty title="No exports yet" />}
          </Card>
        )}
      </div>
    </div>
  );
}
