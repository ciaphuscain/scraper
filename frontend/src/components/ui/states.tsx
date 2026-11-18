import type { ReactNode } from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import { Spinner } from "./primitives";
import { Button } from "./button";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="flex items-center gap-2 p-6 text-sm text-muted"><Spinner />{label}</div>;
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/10 p-4 text-sm">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
      <div className="flex-1">
        <div className="font-medium text-danger">Something went wrong</div>
        <div className="mt-0.5 text-fg/80">{msg}</div>
      </div>
      {onRetry ? <Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button> : null}
    </div>
  );
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      <div className="text-muted">{icon ?? <Inbox className="size-8" />}</div>
      <div className="text-sm font-medium">{title}</div>
      {children ? <div className="max-w-md text-sm text-muted">{children}</div> : null}
    </div>
  );
}
