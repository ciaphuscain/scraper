import { describe, expect, it } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { mockApi, renderWithProviders, sampleChannel, sampleIdea } from "./utils";
import { ChannelsPage } from "@/features/channels/ChannelsPage";
import { AddChannelDialog } from "@/features/channels/AddChannelDialog";
import { VideoTable } from "@/features/videos/VideoTable";
import { TranscriptView } from "@/features/transcripts/TranscriptReader";
import { IdeasPage } from "@/features/ideas/IdeasPage";
import { JobRow } from "@/features/processing/JobRow";
import { ExportForm, validateExport } from "@/features/exports/ExportForm";
import { validateField } from "@/features/settings/settingsForm";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { ErrorState } from "@/components/ui/states";
import { api, ApiError } from "@/services/api";
import { fmtTs, snippetParts } from "@/lib/utils";
import type { Job, Transcript } from "@/types/api";

describe("utils", () => {
  it("formats timestamps and FTS snippets", () => {
    expect(fmtTs(125)).toBe("2:05");
    expect(fmtTs(3725)).toBe("1:02:05");
    expect(snippetParts("a [[b]] c")).toEqual([{ text: "a ", hit: false }, { text: "b", hit: true }, { text: " c", hit: false }]);
  });
});

describe("channel management", () => {
  it("lists channels with real stats", async () => {
    mockApi([{ path: "/api/channels", body: { channels: [sampleChannel], pending_additions: [] } }]);
    renderWithProviders(<ChannelsPage />);
    expect(await screen.findByText("Alpha Finance")).toBeInTheDocument();
    expect(screen.getByText("@alpha UCaaaaaaaaaaaaaaaaaaaaaa")).toBeInTheDocument();
    expect(screen.getByText("100% · 0 pending")).toBeInTheDocument();
  });

  it("submits multiple channel URLs and shows per-URL errors", async () => {
    const fetchMock = mockApi([{ method: "POST", path: "/api/channels/bulk", body: { queued: [{}], errors: [{ url: "bad", error: "Not a YouTube URL" }] } }]);
    renderWithProviders(<AddChannelDialog open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByLabelText("Channel URLs"), "https://www.youtube.com/@a\nbad");
    await userEvent.click(screen.getByRole("button", { name: "Add 2" }));
    expect(await screen.findByText(/Not a YouTube URL/)).toBeInTheDocument();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.urls).toEqual(["https://www.youtube.com/@a", "bad"]);
  });
});

describe("video filtering", () => {
  it("passes filters to the API", async () => {
    const fetchMock = mockApi([{ path: "/api/videos", body: { total: 0, page: 1, page_size: 50, videos: [] } }]);
    renderWithProviders(<VideoTable channelId="UCx" />);
    await screen.findByText("No videos match");
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "short" } });
    await waitFor(() => {
      const last = new URL(String(fetchMock.mock.calls.at(-1)![0]), "http://x");
      expect(last.searchParams.get("video_type")).toBe("short");
      expect(last.searchParams.get("channel_id")).toBe("UCx");
    });
  });
});

describe("transcript rendering", () => {
  const t: Transcript = {
    id: 1, video_id: "v", kind: "source", parent_id: null, method: "auto_captions", language: "en", is_current: true, completeness: "partial",
    coverage_ratio: 0.5, confidence: null, word_count: 6, segment_count: 2, details: {}, created_at: "2024-01-01", has_raw_caption: true,
    segments: [
      { id: "S00000", start: 0, end: 2, text: "hello neural world", confidence: null, url: "https://www.youtube.com/watch?v=v&t=0s" },
      { id: "S00001", start: 65, end: 70, text: "gradient descent", confidence: null, url: "https://www.youtube.com/watch?v=v&t=65s" },
    ],
  };
  it("shows timestamped segments with links, incompleteness warning, and search hits", async () => {
    renderWithProviders(<TranscriptView transcript={t} />);
    expect(screen.getByText("Auto captions")).toBeInTheDocument();
    expect(screen.getByText(/may be incomplete/)).toBeInTheDocument();
    const link = screen.getByText("1:05").closest("a")!;
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch?v=v&t=65s");
    await userEvent.type(screen.getByLabelText("Search transcript"), "neural");
    expect(screen.getByText("1/1")).toBeInTheDocument();
    expect(document.querySelector("mark")?.textContent).toBe("neural");
    fireEvent.change(screen.getByLabelText("View mode"), { target: { value: "plain" } });
    expect(screen.getByText(/gradient descent/)).toBeInTheDocument();
  });
});

describe("idea search", () => {
  it("searches ideas and renders source-linked cards", async () => {
    const fetchMock = mockApi([
      { path: "/api/channels", body: { channels: [sampleChannel], pending_additions: [] } },
      { path: "/api/ideas/facets", body: { topics: [], idea_types: [], tags: [] } },
      { path: "/api/ideas", body: (u: URL) => ({ total: u.searchParams.get("q") ? 1 : 0, page: 1, page_size: 50, ideas: u.searchParams.get("q") ? [sampleIdea] : [] }) },
    ]);
    renderWithProviders(<IdeasPage />);
    await screen.findByText("No ideas found");
    await userEvent.type(screen.getByLabelText("Search ideas"), "interest");
    expect(await screen.findByText("Compound interest grows savings")).toBeInTheDocument();
    expect(screen.getByText("Creator claim (unverified)")).toBeInTheDocument();
    expect(screen.getByText("0:04–0:09").closest("a")).toHaveAttribute("href", sampleIdea.url);
    const call = fetchMock.mock.calls.map((c) => new URL(String(c[0]), "http://x")).find((u) => u.pathname === "/api/ideas" && u.searchParams.get("q"));
    expect(call?.searchParams.get("sort")).toBe("relevance");
  });
});

describe("job status display", () => {
  const job: Job = {
    id: 5, job_type: "transcribe_audio", lane: "cpu", channel_id: "c", video_id: "vid", video_title: "My video", channel_name: "Chan",
    priority: 0, status: "running", stage: "transcribing", progress: 0.4, attempts: 1, max_attempts: 4, run_after: "2024-01-01T00:00:00",
    error_kind: null, error_message: null, created_at: "2024-01-01T00:00:00", started_at: "2024-01-01T00:00:00", finished_at: null,
    heartbeat_at: null, requested_action: null, result: null, payload: {},
  };
  it("shows stage, progress and controls; failed jobs show error and retry", () => {
    mockApi([]);
    const { rerender } = renderWithProviders(<JobRow job={job} />);
    expect(screen.getByText("Transcribe (Whisper)")).toBeInTheDocument();
    expect(screen.getByText("transcribing")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByLabelText("Pause job")).toBeInTheDocument();
    rerender(<JobRow job={{ ...job, status: "failed", error_message: "The video is private." }} />);
    expect(screen.getByText("The video is private.")).toBeInTheDocument();
    expect(screen.getByLabelText("Retry job")).toBeInTheDocument();
  });
});

describe("settings validation", () => {
  it("validates numeric bounds client-side", () => {
    expect(validateField({ type: "integer", minimum: 1, maximum: 8 }, 9)).toBe("Maximum 8");
    expect(validateField({ type: "integer" }, 1.5)).toBe("Must be a whole number");
    expect(validateField({ type: "number" }, "")).toBe("Must be a number");
    expect(validateField({ type: "array" }, [])).toBe("At least one value required");
    expect(validateField({ type: "integer", minimum: 1 }, 2)).toBeNull();
  });

  it("blocks saving invalid values and shows server field errors", async () => {
    mockApi([
      { path: "/api/settings", body: { values: { download_concurrency: 2, ollama_url: "http://x" }, effective_archive_dir: "/a",
        schema: { download_concurrency: { type: "integer", minimum: 1, maximum: 8 }, ollama_url: { type: "string" } } } },
      { path: "/api/ollama/models", body: { online: false, models: [] } },
      { method: "PUT", path: "/api/settings", status: 422, body: { detail: { errors: [{ field: "ollama_url", message: "must start with http" }] } } },
    ]);
    renderWithProviders(<SettingsPage />);
    const input = await screen.findByLabelText("download concurrency");
    fireEvent.change(input, { target: { value: "20" } });
    expect(screen.getByText("Maximum 8")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save settings/ })).toBeDisabled();
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("ollama url"), { target: { value: "ftp://bad" } });
    await userEvent.click(screen.getByRole("button", { name: /Save settings/ }));
    expect(await screen.findByText("must start with http")).toBeInTheDocument();
  });
});

describe("export selection", () => {
  it("validates export specs", () => {
    expect(validateExport({ scope: "channels", ids: [], content: ["ideas"], format: "zip" })).toMatch(/channel/);
    expect(validateExport({ scope: "all", ids: [], content: [], format: "json" })).toMatch(/content/);
    expect(validateExport({ scope: "all", ids: [], content: [], format: "sqlite" })).toBeNull();
  });
  it("submits selected channels and content", async () => {
    mockApi([{ path: "/api/channels", body: { channels: [sampleChannel], pending_additions: [] } }]);
    let submitted: unknown = null;
    renderWithProviders(<ExportForm onSubmit={(s) => (submitted = s)} />);
    fireEvent.change(screen.getByLabelText("Scope"), { target: { value: "channels" } });
    expect(screen.getByRole("button", { name: "Create export" })).toBeDisabled();
    await userEvent.click(await screen.findByLabelText("Alpha Finance"));
    await userEvent.click(screen.getByLabelText("transcripts"));
    fireEvent.change(screen.getByLabelText("Format"), { target: { value: "json" } });
    await userEvent.click(screen.getByRole("button", { name: "Create export" }));
    expect(submitted).toEqual({ scope: "channels", ids: [sampleChannel.id], content: ["metadata", "ideas", "summaries"], format: "json" });
  });
});

describe("error handling", () => {
  it("surfaces backend error details and network failures", async () => {
    mockApi([{ path: "/api/x", status: 400, body: { detail: "Not a channel URL" } }]);
    await expect(api.get("/api/x")).rejects.toThrow("Not a channel URL");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    const err = await api.get("/api/y").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/Cannot reach the backend/);
  });
  it("renders error state with retry", async () => {
    let retried = false;
    renderWithProviders(<Routes><Route path="/" element={<ErrorState error={new Error("boom")} onRetry={() => (retried = true)} />} /></Routes>);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retried).toBe(true);
  });
});
