import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, RotateCcw, Save, XCircle } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Checkbox, Input, Label, Select, Textarea } from "@/components/ui/primitives";
import { ErrorState, Loading } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSystem } from "@/hooks/queries";
import { useAction } from "@/hooks/useAction";
import { ApiError, api } from "@/services/api";
import type { Prompt, SettingsSchemaProp } from "@/types/api";
import { useUI } from "@/stores/ui";
import { label } from "@/lib/utils";
import { GROUPS, enumValues, fieldKind, validateField } from "./settingsForm";

type SettingsRes = { values: Record<string, unknown>; schema: Record<string, SettingsSchemaProp>; effective_archive_dir: string };

function Field({ name, prop, value, onChange, error, models }: {
  name: string; prop: SettingsSchemaProp; value: unknown; onChange: (v: unknown) => void; error?: string | null; models?: string[];
}) {
  const k = fieldKind(prop);
  const id = `set-${name}`;
  let control;
  if (k === "bool") control = <Checkbox id={id} checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
  else if (k === "enum") control = <Select id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>{enumValues(prop).map((v) => <option key={v} value={v}>{v}</option>)}</Select>;
  else if (k === "list") control = <Input id={id} value={(value as string[] | undefined)?.join(", ") ?? ""} onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
  else if (k === "int" || k === "float") control = <Input id={id} type="number" step={k === "float" ? "0.1" : "1"} className="w-32" value={String(value ?? "")} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />;
  else if (name === "ollama_model" && models?.length) control = (
    <><Input id={id} list="ollama-models" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      <datalist id="ollama-models">{models.map((m) => <option key={m} value={m} />)}</datalist></>
  );
  else control = <Input id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} placeholder={name === "output_dir" ? "default archive folder" : name === "whisper_language" ? "auto-detect" : undefined} />;
  return (
    <div className={k === "bool" ? "flex items-start gap-2" : "space-y-1"}>
      {k === "bool" && control}
      <div className="flex-1">
        <Label htmlFor={id} className="text-fg">{label(name)}</Label>
        {prop.description && <div className="text-xs text-muted">{prop.description}</div>}
        {k !== "bool" && <div className="mt-1">{control}</div>}
        {error && <div className="mt-0.5 text-xs text-danger" role="alert">{error}</div>}
      </div>
    </div>
  );
}

function GeneralSettings() {
  const toast = useUI((s) => s.toast);
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api.get<SettingsRes>("/api/settings") });
  const models = useQuery({ queryKey: ["ollamaModels"], queryFn: () => api.get<{ online: boolean; models: { name: string }[]; error?: string }>("/api/ollama/models") });
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  useEffect(() => { if (q.data) setDraft(q.data.values); }, [q.data]);
  const errors = useMemo(() => {
    const out: Record<string, string> = {};
    if (!q.data) return out;
    for (const [k, p] of Object.entries(q.data.schema)) {
      const e = validateField(p, draft[k]);
      if (e) out[k] = e;
    }
    return out;
  }, [draft, q.data]);
  const save = useAction(async () => {
    setServerErrors({});
    const changed = Object.fromEntries(Object.entries(draft).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(q.data?.values[k])));
    try {
      return await api.put("/api/settings", changed);
    } catch (e) {
      if (e instanceof ApiError && e.fieldErrors) setServerErrors(Object.fromEntries(e.fieldErrors.map((f) => [f.field, f.message])));
      throw e;
    }
  }, "Settings saved");
  const test = useAction(() => api.post<{ ok: boolean; message?: string; version?: string; model?: string }>("/api/ollama/test", { url: draft.ollama_url, model: draft.ollama_model }));
  if (q.isLoading) return <Loading />;
  if (q.error || !q.data) return <ErrorState error={q.error} />;
  const dirty = JSON.stringify(draft) !== JSON.stringify(q.data.values);
  return (
    <div className="space-y-4">
      {GROUPS.map((g) => (
        <Card key={g.title}>
          <CardHeader><CardTitle>{g.title}</CardTitle>
            {g.title.startsWith("Local AI") && (
              <div className="flex items-center gap-2">
                {test.data && (test.data.ok ? <span className="flex items-center gap-1 text-xs text-ok"><CheckCircle2 className="size-4" />Ollama {test.data.version} · {test.data.model} works</span>
                  : <span className="flex items-center gap-1 text-xs text-danger"><XCircle className="size-4" />{test.data.message}</span>)}
                <Button size="sm" variant="secondary" onClick={() => test.mutate(undefined)} disabled={test.isPending}>{test.isPending ? "Testing…" : "Test connection"}</Button>
              </div>
            )}
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            {g.keys.filter((k) => q.data.schema[k]).map((k) => (
              <Field key={k} name={k} prop={q.data.schema[k]} value={draft[k]} onChange={(v) => setDraft({ ...draft, [k]: v })}
                error={errors[k] ?? serverErrors[k]} models={models.data?.models.map((m) => m.name)} />
            ))}
            {g.title.startsWith("Files") && <div className="text-xs text-muted md:col-span-2">Current archive folder: <span className="font-mono">{q.data.effective_archive_dir}</span></div>}
            {g.title.startsWith("Local AI") && models.data && !models.data.online && <div className="text-xs text-warn md:col-span-2">Ollama is offline. Transcript collection continues; analysis jobs wait until it is available.</div>}
          </CardContent>
        </Card>
      ))}
      {serverErrors.settings && <ErrorState error={serverErrors.settings} />}
      <div className="sticky bottom-0 flex gap-2 border-t border-border bg-bg py-3">
        <Button disabled={!dirty || Object.keys(errors).length > 0 || save.isPending} onClick={() => save.mutate(undefined, { onError: () => toast("Settings were not saved", "error") })}><Save />Save settings</Button>
        <Button variant="secondary" disabled={!dirty} onClick={() => setDraft(q.data.values)}>Discard changes</Button>
      </div>
    </div>
  );
}

function PromptEditor({ p }: { p: Prompt }) {
  const [body, setBody] = useState(p.body);
  useEffect(() => setBody(p.body), [p.body]);
  const save = useAction(() => api.put<{ version: number }>(`/api/prompts/${p.key}`, { body }), (r) => `Saved as version ${r.version}`);
  const reset = useAction(() => api.post<{ version: number }>(`/api/prompts/${p.key}/reset`), "Reset to default");
  return (
    <Card>
      <CardHeader>
        <div><CardTitle>{label(p.key)}</CardTitle><div className="text-xs text-muted">{p.description}</div></div>
        <div className="flex items-center gap-2"><Badge tone={p.is_default ? "muted" : "accent"}>v{p.version}{p.is_default ? " · default" : " · custom"}</Badge>
          <Button size="sm" variant="secondary" onClick={() => reset.mutate(undefined)}><RotateCcw />Reset</Button>
          <Button size="sm" disabled={body === p.body} onClick={() => save.mutate(undefined)}><Save />Save</Button></div>
      </CardHeader>
      <CardContent><Textarea aria-label={`${p.key} prompt`} rows={10} className="font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} /></CardContent>
    </Card>
  );
}

function Prompts() {
  const q = useQuery({ queryKey: ["prompts"], queryFn: () => api.get<{ prompts: Prompt[] }>("/api/prompts") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Prompts are versioned; each analysis records which versions were used. Placeholders like <code>{"{{chunk_text}}"}</code> are required.</p>
      {q.data?.prompts.map((p) => <PromptEditor key={p.key} p={p} />)}
    </div>
  );
}

function SystemInfo() {
  const s = useSystem();
  if (!s.data) return <Loading />;
  const d = s.data;
  const row = (k: string, v: React.ReactNode) => <div className="flex justify-between gap-4 py-1.5"><span className="text-muted">{k}</span><span className="text-right font-mono text-xs">{v}</span></div>;
  return (
    <Card><CardContent className="divide-y divide-border text-sm">
      {row("Worker", d.worker.online ? "running" : "not running")}
      {row("Ollama", d.ollama.online ? `online (${d.ollama.version})` : `offline — ${d.ollama.url}`)}
      {row("FFmpeg", d.ffmpeg ? "found" : "missing (install and add to PATH)")}
      {row("faster-whisper", d.faster_whisper ? "installed" : "missing")}
      {row("yt-dlp", d.yt_dlp ?? "missing")}
      {row("Python", d.python)}
      {row("Database", d.database)}
      {row("Archive folder", d.archive_dir)}
      {row("Free disk", `${d.disk_free_gb} GB`)}
    </CardContent></Card>
  );
}

export function SettingsPage() {
  return (
    <div className="pb-8">
      <PageHeader title="Settings" />
      <div className="px-6">
        <Tabs defaultValue="general">
          <TabsList><TabsTrigger value="general">General</TabsTrigger><TabsTrigger value="prompts">AI prompts</TabsTrigger><TabsTrigger value="system">System</TabsTrigger></TabsList>
          <TabsContent value="general" className="pt-4"><GeneralSettings /></TabsContent>
          <TabsContent value="prompts" className="pt-4"><Prompts /></TabsContent>
          <TabsContent value="system" className="pt-4"><SystemInfo /></TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
