import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/** Mutation that invalidates keys and toasts the outcome, the one convention for every form.
 * `invalidate` is read again before the mutation counts as done; `refresh` is read again in the
 * background, for lists the next view does not need. `action` puts a button on the success
 * toast, for a way to what the mutation started. */
export function useMutationToast<TData, TVariables>(options: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  invalidate?: QueryKey[];
  refresh?: QueryKey[];
  success?: string | ((data: TData) => string);
  action?: { label: string; onClick: () => void };
  onSuccess?: (data: TData, variables: TVariables) => void;
  onError?: (error: Error, variables: TVariables) => void;
}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: options.mutationFn,
    onSuccess: async (data, variables) => {
      for (const key of options.refresh ?? []) void client.invalidateQueries({ queryKey: key });
      await Promise.all((options.invalidate ?? []).map((key) => client.invalidateQueries({ queryKey: key })));
      if (options.success)
        toast.success(typeof options.success === "function" ? options.success(data) : options.success, {
          action: options.action,
        });
      options.onSuccess?.(data, variables);
    },
    onError: (error: Error, variables) => {
      if (options.onError) options.onError(error, variables);
      else toast.error(error.message);
    },
  });
}
