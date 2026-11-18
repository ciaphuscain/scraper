import { NavLink, Outlet } from "react-router-dom";
import {
  BarChart3, Download, Film, Gauge, Lightbulb, ListChecks, Moon, PanelLeftClose, PanelLeftOpen, Search, Settings, Sun, Tv, X,
} from "lucide-react";
import { useUI } from "@/stores/ui";
import { useSystem } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/channels", label: "Channels", icon: Tv },
  { to: "/videos", label: "Videos", icon: Film },
  { to: "/ideas", label: "Idea Explorer", icon: Lightbulb },
  { to: "/search", label: "Search", icon: Search },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/queue", label: "Processing", icon: ListChecks },
  { to: "/exports", label: "Exports", icon: Download },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Dot({ ok, label, title }: { ok: boolean | undefined; label: string; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted" title={title}>
      <span className={cn("size-2 rounded-full", ok === undefined ? "bg-muted" : ok ? "bg-ok" : "bg-danger")} />
      {label}
    </span>
  );
}

export function Layout() {
  const { sidebarCollapsed, toggleSidebar, theme, setTheme, toasts, dismiss } = useUI();
  const sys = useSystem();
  const s = sys.data;
  return (
    <div className="flex h-full">
      <aside className={cn("flex shrink-0 flex-col border-r border-border bg-panel transition-[width]", sidebarCollapsed ? "w-14" : "w-56")}>
        <div className="flex h-12 items-center gap-2 border-b border-border px-3">
          <div className="grid size-7 shrink-0 place-items-center rounded bg-accent text-xs font-bold text-accent-fg">CS</div>
          {!sidebarCollapsed && <div className="truncate text-sm font-semibold">Content Studio</div>}
        </div>
        <nav className="flex-1 space-y-0.5 p-2" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} title={label}
              className={({ isActive }) => cn("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm",
                isActive ? "bg-accent/15 text-accent" : "text-muted hover:bg-panel-2 hover:text-fg")}>
              <Icon className="size-4 shrink-0" />
              {!sidebarCollapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-1 border-t border-border p-2">
          <Button variant="ghost" size="icon" onClick={toggleSidebar} aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle theme">
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-end gap-4 border-b border-border bg-panel px-4">
          {sys.isError ? <span className="text-xs text-danger">Backend unreachable</span> : <>
            {s?.queue_paused && <span className="text-xs font-medium text-warn">Queue paused</span>}
            <Dot ok={s?.worker.online} label="Worker" title={s?.worker.online ? "Processing worker running" : "Worker offline — start it with start.ps1"} />
            <Dot ok={s?.ollama.online} label={`Ollama${s?.ollama.online ? ` · ${s.ollama.model}` : ""}`} title={s?.ollama.url} />
            <Dot ok={s?.ffmpeg} label="FFmpeg" />
          </>}
        </header>
        <main className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
            className={cn("flex items-start gap-2 rounded-md border bg-panel p-3 text-sm shadow-lg",
              t.kind === "error" ? "border-danger/40" : t.kind === "success" ? "border-ok/40" : "border-border")}>
            <span className="flex-1">{t.message}</span>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-muted hover:text-fg"><X className="size-4" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 px-6 pb-4 pt-5">
      <div className="min-w-0">
        <h1 className="truncate text-lg font-semibold">{title}</h1>
        {subtitle ? <div className="mt-0.5 text-sm text-muted">{subtitle}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
