import { Link } from "react-router-dom";
import { Pause, Play, RotateCcw, X } from "lucide-react";
import type { Job } from "@/types/api";
import { Progress } from "@/components/ui/primitives";
import { StatusBadge } from "@/components/ui/status";
import { Button } from "@/components/ui/button";
import { elapsed, label, relTime } from "@/lib/utils";
import { useAction } from "@/hooks/useAction";
import { api } from "@/services/api";

export const JOB_NAMES: Record<string, string> = {
  discover_channel: "Discover channel", fetch_transcript: "Collect captions", download_audio: "Download audio",
  transcribe_audio: "Transcribe (Whisper)", analyze_video: "Extract ideas", channel_report: "Channel report",
  cross_channel_report: "Cross-channel comparison", export: "Export",
};

export function JobActions({ job, compact }: { job: Job; compact?: boolean }) {
  const act = useAction(({ id, action }: { id: number; action: string }) => api.post(`/api/jobs/${id}/${action}`));
  const sz = compact ? "sm" : "sm";
  return (
    <div className="flex items-center gap-1">
      {["queued", "retry_scheduled", "running"].includes(job.status) && (
        <Button size={sz} variant="ghost" title="Pause" aria-label="Pause job" onClick={() => act.mutate({ id: job.id, action: "pause" })}><Pause /></Button>
      )}
      {job.status === "paused" && (
        <Button size={sz} variant="ghost" title="Resume" aria-label="Resume job" onClick={() => act.mutate({ id: job.id, action: "resume" })}><Play /></Button>
      )}
      {["failed", "cancelled"].includes(job.status) && (
        <Button size={sz} variant="ghost" title="Retry" aria-label="Retry job" onClick={() => act.mutate({ id: job.id, action: "retry" })}><RotateCcw /></Button>
      )}
      {["queued", "retry_scheduled", "running", "paused"].includes(job.status) && (
        <Button size={sz} variant="ghost" title="Cancel" aria-label="Cancel job" onClick={() => act.mutate({ id: job.id, action: "cancel" })}><X /></Button>
      )}
    </div>
  );
}

export function JobRow({ job }: { job: Job }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{JOB_NAMES[job.job_type] ?? job.job_type}</span>
          <StatusBadge status={job.status} />
          {job.status === "running" && <span className="text-xs text-muted">{label(job.stage)}</span>}
        </div>
        <div className="mt-0.5 truncate text-xs text-muted">
          {job.video_id ? <Link className="hover:text-fg" to={`/videos/${job.video_id}`}>{job.video_title || job.video_id}</Link> : null}
          {job.channel_name ? <> · {job.channel_name}</> : null}
          {job.status === "retry_scheduled" ? <> · retry {relTime(job.run_after).replace(" ago", "")}</> : null}
        </div>
        {job.error_message && job.status !== "completed" && <div className="mt-0.5 text-xs text-danger">{job.error_message}</div>}
        {job.status === "running" && <Progress className="mt-1.5" value={job.progress} />}
      </div>
      <div className="hidden w-24 text-right text-xs text-muted sm:block">
        {job.started_at ? elapsed(job.started_at, job.finished_at) : relTime(job.created_at)}
        <div>try {job.attempts}/{job.max_attempts}</div>
      </div>
      <JobActions job={job} compact />
    </div>
  );
}
