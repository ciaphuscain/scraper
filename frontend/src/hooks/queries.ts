import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import type { Channel, Dashboard, Idea, IdeaDetail, Job, Paged, SystemStatus, Transcript, Video, VideoDetail } from "@/types/api";

type P = Record<string, string | number | boolean | undefined | null>;

export const useSystem = () => useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemStatus>("/api/system/status"), refetchInterval: 10000 });
export const useDashboard = () => useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/api/dashboard"), refetchInterval: 4000 });
export const useChannels = (includeInactive = false) =>
  useQuery({ queryKey: ["channels", includeInactive], queryFn: () => api.get<{ channels: Channel[]; pending_additions: Job[] }>("/api/channels", { include_inactive: includeInactive }), refetchInterval: 5000 });
export const useChannel = (id: string) => useQuery({ queryKey: ["channel", id], queryFn: () => api.get<Channel>(`/api/channels/${id}`), refetchInterval: 5000 });
export const useVideos = (params: P) =>
  useQuery({ queryKey: ["videos", params], queryFn: () => api.get<Paged<"videos", Video>>("/api/videos", params), placeholderData: keepPreviousData, refetchInterval: 8000 });
export const useVideo = (id: string) => useQuery({ queryKey: ["video", id], queryFn: () => api.get<VideoDetail>(`/api/videos/${id}`), refetchInterval: 5000 });
export const useTranscript = (videoId: string, transcriptId?: number, enabled = true) =>
  useQuery({ queryKey: ["transcript", videoId, transcriptId], queryFn: () => api.get<Transcript>(`/api/videos/${videoId}/transcript`, { transcript_id: transcriptId }), enabled });
export const useVideoIdeas = (videoId: string) => useQuery({ queryKey: ["videoIdeas", videoId], queryFn: () => api.get<{ ideas: Idea[] }>(`/api/videos/${videoId}/ideas`) });
export const useIdeas = (params: P) =>
  useQuery({ queryKey: ["ideas", params], queryFn: () => api.get<Paged<"ideas", Idea>>("/api/ideas", params), placeholderData: keepPreviousData });
export const useIdea = (id: number | null) => useQuery({ queryKey: ["idea", id], queryFn: () => api.get<IdeaDetail>(`/api/ideas/${id}`), enabled: id != null });
export const useJobs = (params: P) =>
  useQuery({ queryKey: ["jobs", params], queryFn: () => api.get<Paged<"jobs", Job>>("/api/jobs", params), placeholderData: keepPreviousData, refetchInterval: 3000 });
