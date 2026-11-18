import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { Layout } from "./Layout";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ChannelsPage } from "@/features/channels/ChannelsPage";
import { ChannelDetailPage } from "@/features/channels/ChannelDetailPage";
import { VideosPage } from "@/features/videos/VideosPage";
import { VideoDetailPage } from "@/features/videos/VideoDetailPage";
import { IdeasPage } from "@/features/ideas/IdeasPage";
import { SearchPage } from "@/features/search/SearchPage";
import { QueuePage } from "@/features/processing/QueuePage";
import { ReportsPage } from "@/features/reports/ReportsPage";
import { ExportsPage } from "@/features/exports/ExportsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { Empty } from "@/components/ui/states";

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 2000 } } });
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="channels" element={<ChannelsPage />} />
        <Route path="channels/:id" element={<ChannelDetailPage />} />
        <Route path="videos" element={<VideosPage />} />
        <Route path="videos/:id" element={<VideoDetailPage />} />
        <Route path="ideas" element={<IdeasPage />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="exports" element={<ExportsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Empty title="Page not found" />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <TooltipProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
