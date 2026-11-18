export type Job = {
  id: number; job_type: string; lane: string; channel_id: string | null; video_id: string | null;
  video_title?: string | null; channel_name?: string | null; priority: number; status: string; stage: string;
  progress: number; attempts: number; max_attempts: number; run_after: string; error_kind: string | null;
  error_message: string | null; created_at: string; started_at: string | null; finished_at: string | null;
  heartbeat_at: string | null; requested_action: string | null; result: Record<string, unknown> | null;
  payload: Record<string, unknown>;
};

export type ChannelStats = {
  videos: number; shorts: number; transcripts: number; analysed: number; failed: number; unavailable: number;
  pending: number; ideas: number; processed: number; progress: number; active_jobs?: number;
};

export type Channel = ChannelStats & {
  id: string; name: string; handle: string | null; url: string; description: string | null;
  thumbnail_url: string | null; subscriber_count: number | null; active: boolean; paused: boolean; priority: number;
  scan_since: string | null; auto_process: boolean; last_scan_at: string | null; last_sync_at: string | null;
  last_scan_error: string | null; created_at: string;
  latest_report?: { id: number; created_at: string } | null; recent_jobs?: Job[];
};

export type Video = {
  id: string; channel_id: string | null; channel_name: string | null; title: string; url: string;
  upload_date: string | null; upload_date_approximate: boolean; duration: number | null; thumbnail_url: string | null;
  video_type: "video" | "short" | "live"; type_source: string; language: string | null;
  has_manual_subs: boolean | null; has_auto_subs: boolean | null; availability: string; selected: boolean;
  transcript_status: string; analysis_status: string; idea_count: number; last_error: string | null;
  discovered_at: string; view_count: number | null;
};

export type TranscriptInfo = {
  id: number; video_id: string; kind: string; parent_id: number | null; method: string; language: string | null;
  is_current: boolean; completeness: string; coverage_ratio: number | null; confidence: number | null;
  word_count: number; segment_count: number; details: Record<string, unknown>; created_at: string;
  has_raw_caption: boolean;
};

export type Segment = { id: string; start: number; end: number; text: string; confidence: number | null; url: string };
export type Transcript = TranscriptInfo & { segments: Segment[] };

export type Analysis = {
  id: number; model: string; analysis_version: string; prompt_versions: Record<string, number>;
  main_theme: string | null; central_thesis: string | null; summary: string | null; topics: string[];
  takeaways: string[]; relationships: { source: number; target: number; relation: string }[];
  validation: Record<string, unknown>; chunk_count: number; raw_idea_count: number; created_at: string;
};

export type VideoDetail = Video & {
  description: string | null; tags: string[] | null; subtitle_languages: string[] | null; listing_sources: string[];
  channel: { id: string; name: string; url: string } | null; transcripts: TranscriptInfo[];
  analysis: Analysis | null; jobs: Job[];
  orphaned_annotations: { id: number; idea_title: string; note: string | null; tags: string[]; bookmarked: boolean }[];
};

export type Annotation = { id: number; note: string | null; tags: string[]; bookmarked: boolean; updated_at: string };

export type Excerpt = { text: string; segment_key: string; start: number; verified: boolean; source?: string };

export type Idea = {
  id: number; video_id: string; video_title: string | null; channel_id: string | null; channel_name: string | null;
  ordinal: number; title: string; explanation: string; idea_type: string; topic: string | null; keywords: string[];
  segment_ids: string[]; start_time: number | null; end_time: number | null; excerpts: Excerpt[];
  statement_kind: string; confidence: number | null; uncertainty: string | null; model: string;
  analysis_version: string; video_type: string | null; upload_date: string | null; created_at: string; url: string;
  annotation: Annotation | null;
};

export type IdeaDetail = Idea & { source_segments: Segment[] };

export type Paged<K extends string, T> = { total: number; page: number; page_size: number } & Record<K, T[]>;

export type SearchResult = {
  kind: "ideas" | "segments" | "videos" | "channels"; snippet: string; title?: string; video_id?: string;
  video_title?: string; channel_id?: string; channel_name?: string; start?: number; url?: string;
  idea_id?: number; seg_key?: string; idea_type?: string; topic?: string; upload_date?: string; video_type?: string;
};

export type SystemStatus = {
  worker: { online: boolean; status: Record<string, unknown> | null };
  ollama: { online: boolean; version: string | null; url: string; model: string };
  ffmpeg: boolean; faster_whisper: boolean; yt_dlp: string | null; python: string; platform: string;
  database: string; archive_dir: string; disk_free_gb: number; queue_paused: boolean;
};

export type Dashboard = {
  channels: number; videos: number; shorts: number; transcripts: number; ideas: number; analysed_videos: number;
  unavailable: number;
  jobs: { pending: number; active: number; failed: number; completed: number; paused: number; retry_scheduled: number };
  active_jobs: Job[]; recent_failures: Job[]; recent_channels: Channel[];
};

export type ExportRecord = {
  id: number; job_id: number | null; scope: string; target_ids: string[]; content: string[]; format: string;
  status: string; file_name: string | null; size_bytes: number | null; item_count: number | null; error: string | null;
  created_at: string; finished_at: string | null;
};

export type SettingsSchemaProp = {
  type?: string; title?: string; description?: string; default?: unknown; minimum?: number; maximum?: number;
  enum?: string[]; anyOf?: { type?: string; enum?: string[] }[]; items?: { type?: string };
};

export type Prompt = { key: string; description: string; version: number; body: string; is_default: boolean; updated_at: string };
