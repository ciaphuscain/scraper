import { create } from "zustand";
import { persist } from "zustand/middleware";

type Toast = { id: number; kind: "info" | "error" | "success"; message: string };

type UIState = {
  sidebarCollapsed: boolean;
  theme: "dark" | "light";
  toasts: Toast[];
  toggleSidebar: () => void;
  setTheme: (t: "dark" | "light") => void;
  toast: (message: string, kind?: Toast["kind"]) => void;
  dismiss: (id: number) => void;
};

let nextId = 1;

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: "dark",
      toasts: [],
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setTheme: (theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        try {
          localStorage.setItem("ytcs-theme", theme);
        } catch {
          /* ignore */
        }
        set({ theme });
      },
      toast: (message, kind = "info") => {
        const id = nextId++;
        set((s) => ({ toasts: [...s.toasts, { id, kind, message }] }));
        setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), kind === "error" ? 8000 : 4000);
      },
      dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
    }),
    { name: "ytcs-ui", partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, theme: s.theme }) },
  ),
);

/** Ideas selected for export from the Idea Explorer. */
type SelectionState = { ideaIds: number[]; toggle: (id: number) => void; clear: () => void; set: (ids: number[]) => void };
export const useIdeaSelection = create<SelectionState>()((set) => ({
  ideaIds: [],
  toggle: (id) => set((s) => ({ ideaIds: s.ideaIds.includes(id) ? s.ideaIds.filter((x) => x !== id) : [...s.ideaIds, id] })),
  clear: () => set({ ideaIds: [] }),
  set: (ids) => set({ ideaIds: ids }),
}));
