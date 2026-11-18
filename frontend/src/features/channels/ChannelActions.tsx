import { useState } from "react";
import { Pause, Play, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import type { Channel } from "@/types/api";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/primitives";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";

export function ChannelActions({ channel, onRemoved }: { channel: Channel; onRemoved?: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [purge, setPurge] = useState(false);
  const id = channel.id;
  const scan = useAction(() => api.post(`/api/channels/${id}/scan`, {}), "Scan for new uploads queued");
  const pause = useAction(() => api.post(`/api/channels/${id}/${channel.paused ? "resume" : "pause"}`), channel.paused ? "Channel resumed" : "Channel paused");
  const retry = useAction(() => api.post<{ retried: number }>(`/api/channels/${id}/retry`), (r) => `Retrying ${r.retried} failed job(s)`);
  const remove = useAction(() => api.del(`/api/channels/${id}`, { purge }), "Channel removed");
  return (
    <div className="flex items-center gap-1">
      <Button size="sm" variant="ghost" title="Scan for new uploads" aria-label="Refresh" onClick={() => scan.mutate(undefined)}><RefreshCw /></Button>
      <Button size="sm" variant="ghost" title={channel.paused ? "Resume" : "Pause"} aria-label={channel.paused ? "Resume" : "Pause"} onClick={() => pause.mutate(undefined)}>
        {channel.paused ? <Play /> : <Pause />}
      </Button>
      <Button size="sm" variant="ghost" title="Retry failed" aria-label="Retry failed" onClick={() => retry.mutate(undefined)}><RotateCcw /></Button>
      <Button size="sm" variant="ghost" title="Remove" aria-label="Remove" onClick={() => setConfirm(true)}><Trash2 /></Button>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title={`Remove ${channel.name}?`} destructive confirmLabel="Remove"
        description="The channel is removed from the active library and its pending jobs are cancelled."
        onConfirm={() => remove.mutate(undefined, { onSuccess: () => onRemoved?.() })}>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={purge} onChange={(e) => setPurge(e.target.checked)} />
          Also permanently delete its stored videos, transcripts and ideas
        </label>
      </ConfirmDialog>
    </div>
  );
}
