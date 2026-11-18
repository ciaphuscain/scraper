import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { PageHeader } from "@/app/Layout";
import { Button } from "@/components/ui/button";
import { AddVideoDialog } from "@/features/channels/AddChannelDialog";
import { VideoTable } from "./VideoTable";

export function VideosPage() {
  const [sp] = useSearchParams();
  const [add, setAdd] = useState(false);
  return (
    <div className="pb-8">
      <PageHeader title="Video library" subtitle="All discovered videos and Shorts across channels"
        actions={<Button onClick={() => setAdd(true)}><Plus />Add video</Button>} />
      <div className="px-6">
        <VideoTable initial={{ video_type: sp.get("type") ?? "", transcript_status: sp.get("transcript") ?? "" }} />
      </div>
      <AddVideoDialog open={add} onOpenChange={setAdd} />
    </div>
  );
}
