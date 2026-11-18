export class ApiError extends Error {
  status: number;
  fieldErrors?: { field: string; message: string }[];
  constructor(message: string, status: number, fieldErrors?: { field: string; message: string }[]) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

type Params = Record<string, string | number | boolean | null | undefined>;

export function qs(params?: Params): string {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(params)}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the backend. Is start.ps1 running?", 0);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    let fieldErrors;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (data.detail?.errors) {
        fieldErrors = data.detail.errors;
        msg = data.detail.errors.map((e: { field: string; message: string }) => `${e.field}: ${e.message}`).join("; ");
      } else if (Array.isArray(data.detail)) {
        msg = data.detail.map((e: { loc?: string[]; msg: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status, fieldErrors);
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, undefined, params),
  post: <T>(path: string, body?: unknown, params?: Params) => request<T>("POST", path, body ?? {}, params),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  del: <T>(path: string, params?: Params) => request<T>("DELETE", path, undefined, params),
  url: (path: string, params?: Params) => `${BASE}${path}${qs(params)}`,
};
