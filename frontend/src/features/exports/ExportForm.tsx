import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Checkbox, Label, Select } from "@/components/ui/primitives";
import { useChannels } from "@/hooks/queries";

export type ExportSpec = { scope: string; ids: string[]; content: string[]; format: string };
const CONTENT = ["metadata", "transcripts", "ideas", "summaries"] as const;
export const FORMATS = [
  ["zip", "ZIP archive (folder structure)"], ["json", "JSON"], ["jsonl", "JSONL"], ["csv", "CSV"], ["md", "Markdown"], ["txt", "Plain text"], ["sqlite", "SQLite database backup"],
] as const;

export function validateExport(s: ExportSpec): string | null {
  if (s.format === "sqlite") return null;
  if (!s.content.length) return "Choose at least one kind of content.";
  if (s.scope !== "all" && !s.ids.length) return "Select at least one channel.";
  return null;
}

export function ExportForm({ onSubmit, busy }: { onSubmit: (s: ExportSpec) => void; busy?: boolean }) {
  const channels = useChannels();
  const [scope, setScope] = useState<"all" | "channels">("all");
  const [ids, setIds] = useState<string[]>([]);
  const [content, setContent] = useState<string[]>([...CONTENT]);
  const [format, setFormat] = useState("zip");
  const spec: ExportSpec = { scope, ids, content, format };
  const err = validateExport(spec);
  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap gap-6">
        <div className="space-y-1">
          <Label htmlFor="exp-scope">Scope</Label>
          <Select id="exp-scope" value={scope} onChange={(e) => setScope(e.target.value as "all" | "channels")} disabled={format === "sqlite"}>
            <option value="all">Entire archive</option><option value="channels">Selected channels</option>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="exp-format">Format</Label>
          <Select id="exp-format" value={format} onChange={(e) => setFormat(e.target.value)}>
            {FORMATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </div>
        <fieldset className="space-y-1" disabled={format === "sqlite"}>
          <legend className="text-xs font-medium text-muted">Content</legend>
          <div className="flex gap-3">
            {CONTENT.map((c) => (
              <label key={c} className="flex items-center gap-1.5 text-sm capitalize">
                <Checkbox checked={content.includes(c)} onChange={() => setContent(content.includes(c) ? content.filter((x) => x !== c) : [...content, c])} />{c}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {scope === "channels" && format !== "sqlite" && (
        <div className="flex max-h-40 flex-wrap gap-3 overflow-auto rounded border border-border p-2">
          {channels.data?.channels.map((c) => (
            <label key={c.id} className="flex items-center gap-1.5 text-sm">
              <Checkbox checked={ids.includes(c.id)} onChange={() => setIds(ids.includes(c.id) ? ids.filter((x) => x !== c.id) : [...ids, c.id])} />{c.name}
            </label>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button disabled={!!err || busy} onClick={() => onSubmit(format === "sqlite" ? { ...spec, scope: "all", ids: [] } : spec)}>Create export</Button>
        {err && <span className="text-xs text-warn" role="status">{err}</span>}
      </div>
    </Card>
  );
}
