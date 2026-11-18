import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export type Route = { method?: string; path: string | RegExp; status?: number; body: unknown | ((url: URL, init?: RequestInit) => unknown) };

/** Install a fetch mock that routes by method + path. Returns the mock so tests can inspect calls. */
export function mockApi(routes: Route[]) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const r = routes.find((x) => (x.method ?? "GET") === method && (typeof x.path === "string" ? url.pathname === x.path : x.path.test(url.pathname)));
    if (!r) return new Response(JSON.stringify({ detail: `no mock for ${method} ${url.pathname}` }), { status: 404, headers: { "content-type": "application/json" } });
    const body = typeof r.body === "function" ? (r.body as (u: URL, i?: RequestInit) => unknown)(url, init) : r.body;
    return new Response(JSON.stringify(body), { status: r.status ?? 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export function renderWithProviders(ui: ReactNode, { route = "/" } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(ui, { wrapper });
}

export const sampleChannel = {
  id: "UCaaaaaaaaaaaaaaaaaaaaaa", name: "Alpha Finance", handle: "@alpha", url: "https://www.youtube.com/channel/UCa", description: "",
  thumbnail_url: null, subscriber_count: null, active: true, paused: false, priority: 0, scan_since: null, auto_process: true,
  last_scan_at: null, last_sync_at: null, last_scan_error: null, created_at: "2024-01-01T00:00:00",
  videos: 3, shorts: 2, transcripts: 4, analysed: 4, failed: 1, unavailable: 1, pending: 0, ideas: 10, processed: 4, progress: 1, active_jobs: 0,
};

export const sampleIdea = {
  id: 1, video_id: "vid00000001", video_title: "Compound interest explained", channel_id: sampleChannel.id, channel_name: "Alpha Finance",
  ordinal: 1, title: "Compound interest grows savings", explanation: "Interest earns interest.", idea_type: "main_idea", topic: "Finance",
  keywords: ["compound", "interest"], segment_ids: ["S00001"], start_time: 4, end_time: 9,
  excerpts: [{ text: "Compound interest means", segment_key: "S00001", start: 4, verified: true }], statement_kind: "creator_claim",
  confidence: 0.8, uncertainty: null, model: "m", analysis_version: "1.0", video_type: "video", upload_date: "20240301",
  created_at: "2024-03-01T00:00:00", url: "https://www.youtube.com/watch?v=vid00000001&t=4s", annotation: null,
};
