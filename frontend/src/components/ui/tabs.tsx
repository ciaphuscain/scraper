import * as T from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;
export function TabsList({ className, ...p }: T.TabsListProps) {
  return <T.List className={cn("inline-flex items-center gap-1 border-b border-border", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: T.TabsTriggerProps) {
  return (
    <T.Trigger
      className={cn("-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg cursor-pointer", className)}
      {...p}
    />
  );
}
export const TabsContent = T.Content;
