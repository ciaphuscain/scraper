import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useUI } from "@/stores/ui";

/** Mutation helper: toasts on success/error and invalidates all queries so status stays accurate. */
export function useAction<TArgs, TRes = unknown>(fn: (args: TArgs) => Promise<TRes>, success?: string | ((r: TRes) => string)) {
  const qc = useQueryClient();
  const toast = useUI((s) => s.toast);
  return useMutation({
    mutationFn: fn,
    onSuccess: (res) => {
      if (success) toast(typeof success === "function" ? success(res) : success, "success");
      qc.invalidateQueries();
    },
    onError: (err: Error) => toast(err.message, "error"),
  });
}
