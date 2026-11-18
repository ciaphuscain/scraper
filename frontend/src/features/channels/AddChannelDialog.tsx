import { useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox, Input, Label, Textarea } from "@/components/ui/primitives";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";

type BulkRes = { queued: unknown[]; errors: { url: string; error: string }[] };

export function AddChannelDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [urls, setUrls] = useState("");
  const [since, setSince] = useState("");
  const [auto, setAuto] = useState(true);
  const [errors, setErrors] = useState<BulkRes["errors"]>([]);
  const add = useAction(
    (list: string[]) => api.post<BulkRes>("/api/channels/bulk", { urls: list, scan_since: since || null, auto_process: auto }),
    (r) => `Queued ${r.queued.length} channel(s) for discovery`,
  );
  const lines = urls.split(/\s+/).map((u) => u.trim()).filter(Boolean);
  const submit = () =>
    add.mutate(lines, {
      onSuccess: (r) => {
        setErrors(r.errors);
        if (!r.errors.length) {
          setUrls("");
          onOpenChange(false);
        }
      },
    });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add channels"
      description="Paste one or more channel URLs (@handle, /channel/UC…, /c/name, /user/name), one per line."
      footer={<>
        <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={submit} disabled={!lines.length || add.isPending}>{add.isPending ? "Adding…" : `Add ${lines.length || ""}`}</Button>
      </>}>
      <div className="space-y-3">
        <div className="space-y-1">
          <Label htmlFor="ch-urls">Channel URLs</Label>
          <Textarea id="ch-urls" rows={5} value={urls} onChange={(e) => setUrls(e.target.value)} placeholder="https://www.youtube.com/@channel" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label htmlFor="ch-since">Only uploads since (optional)</Label>
            <Input id="ch-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          </div>
          <label className="flex items-end gap-2 pb-1.5 text-sm">
            <Checkbox checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            Collect transcripts automatically
          </label>
        </div>
        {errors.length > 0 && (
          <ul className="space-y-1 rounded border border-danger/30 bg-danger/10 p-2 text-xs" role="alert">
            {errors.map((e) => <li key={e.url}><span className="font-mono">{e.url}</span>: {e.error}</li>)}
          </ul>
        )}
      </div>
    </Dialog>
  );
}

export function AddVideoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [url, setUrl] = useState("");
  const add = useAction((u: string) => api.post<{ video_id: string }>("/api/videos", { url: u }), (r) => `Queued video ${r.video_id}`);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add a single video" description="Paste a YouTube video or Shorts URL."
      footer={<>
        <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button disabled={!url.trim() || add.isPending} onClick={() => add.mutate(url.trim(), { onSuccess: () => { setUrl(""); onOpenChange(false); } })}>Add video</Button>
      </>}>
      <Input aria-label="Video URL" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
    </Dialog>
  );
}
