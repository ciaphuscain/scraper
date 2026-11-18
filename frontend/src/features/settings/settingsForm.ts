import type { SettingsSchemaProp } from "@/types/api";

export type FieldKind = "bool" | "int" | "float" | "enum" | "list" | "text";

export function fieldKind(p: SettingsSchemaProp): FieldKind {
  if (p.enum) return "enum";
  if (p.anyOf?.some((a) => a.enum)) return "enum";
  if (p.type === "boolean") return "bool";
  if (p.type === "integer") return "int";
  if (p.type === "number") return "float";
  if (p.type === "array") return "list";
  return "text";
}

export function enumValues(p: SettingsSchemaProp): string[] {
  return p.enum ?? p.anyOf?.find((a) => a.enum)?.enum ?? [];
}

/** Client-side validation mirroring server constraints (server remains authoritative). */
export function validateField(p: SettingsSchemaProp, value: unknown): string | null {
  const k = fieldKind(p);
  if (k === "int" || k === "float") {
    const n = Number(value);
    if (value === "" || Number.isNaN(n)) return "Must be a number";
    if (k === "int" && !Number.isInteger(n)) return "Must be a whole number";
    if (p.minimum != null && n < p.minimum) return `Minimum ${p.minimum}`;
    if (p.maximum != null && n > p.maximum) return `Maximum ${p.maximum}`;
  }
  if (k === "list" && Array.isArray(value) && value.length === 0) return "At least one value required";
  return null;
}

export const GROUPS: { title: string; keys: string[] }[] = [
  { title: "Processing & resources", keys: ["download_concurrency", "processing_concurrency", "llm_concurrency", "allow_parallel_heavy", "request_delay_seconds", "max_retries", "auto_process_new_videos", "auto_analyze"] },
  { title: "Transcripts", keys: ["preferred_languages", "allow_auto_captions", "whisper_fallback_enabled", "whisper_model", "whisper_device", "whisper_compute_type", "whisper_language", "whisper_vad", "whisper_beam_size", "whisper_cpu_threads"] },
  { title: "Local AI (Ollama)", keys: ["ollama_url", "ollama_model", "llm_temperature", "llm_context_size", "llm_max_tokens", "llm_timeout_seconds", "llm_retries", "chunk_tokens", "chunk_overlap_segments", "llm_semantic_dedupe"] },
  { title: "Files & exports", keys: ["output_dir", "retain_audio", "cleanup_failed_audio", "write_files_on_completion", "export_default_format", "log_retention_days"] },
];
