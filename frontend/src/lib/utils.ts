import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtTs(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "–";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function fmtDate(d?: string | null): string {
  if (!d) return "–";
  if (/^\d{8}$/.test(d)) return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
  const date = new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z");
  if (Number.isNaN(date.getTime())) return d;
  return date.toLocaleString();
}

export function relTime(d?: string | null): string {
  if (!d) return "never";
  const date = new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z");
  const diff = (Date.now() - date.getTime()) / 1000;
  if (Number.isNaN(diff)) return d;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function elapsed(start?: string | null, end?: string | null): string {
  if (!start) return "–";
  const s = new Date(start + (start.endsWith("Z") ? "" : "Z")).getTime();
  const e = end ? new Date(end + (end.endsWith("Z") ? "" : "Z")).getTime() : Date.now();
  return fmtTs(Math.max(0, (e - s) / 1000));
}

export function fmtBytes(n?: number | null): string {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function ytUrl(videoId: string, t?: number | null) {
  return `https://www.youtube.com/watch?v=${videoId}${t != null ? `&t=${Math.floor(t)}s` : ""}`;
}

export const label = (s?: string | null) => (s ?? "").replace(/_/g, " ");

/** Render FTS snippets: [[term]] -> <mark>. Returns React-safe segments. */
export function snippetParts(snippet: string): { text: string; hit: boolean }[] {
  const parts: { text: string; hit: boolean }[] = [];
  const re = /\[\[(.*?)\]\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(snippet))) {
    if (m.index > last) parts.push({ text: snippet.slice(last, m.index), hit: false });
    parts.push({ text: m[1], hit: true });
    last = m.index + m[0].length;
  }
  if (last < snippet.length) parts.push({ text: snippet.slice(last), hit: false });
  return parts;
}
