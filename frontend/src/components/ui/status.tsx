import { Badge } from "./primitives";
import { label } from "@/lib/utils";

const tone: Record<string, string> = {
  completed: "ok", running: "accent", in_progress: "accent", queued: "muted", pending: "muted",
  retry_scheduled: "warn", failed: "danger", unavailable: "warn", paused: "warn", cancelled: "muted", skipped: "muted",
};

export function StatusBadge({ status, title }: { status: string; title?: string }) {
  return <Badge tone={tone[status] ?? "default"} title={title}>{label(status)}</Badge>;
}

export function TypeBadge({ type }: { type: string }) {
  return <Badge tone={type === "short" ? "accent" : type === "live" ? "warn" : "default"}>{type === "short" ? "Short" : type === "live" ? "Live" : "Video"}</Badge>;
}

export function MethodBadge({ method }: { method: string }) {
  const names: Record<string, string> = { manual_captions: "Creator captions", auto_captions: "Auto captions", whisper: "Local Whisper", ai_correction: "AI-corrected" };
  return <Badge tone={method === "manual_captions" ? "ok" : method === "whisper" ? "accent" : "default"}>{names[method] ?? method}</Badge>;
}
