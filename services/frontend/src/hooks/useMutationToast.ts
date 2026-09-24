import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/** Mutation that invalidates keys and toasts the outcome, the one convention for every form.
 * `action` puts a button on the success toast, for a way to what the mutation started. */
export function useMutationToast<TData, TVariables>(options: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  invalidate?: QueryKey[];
  success?: string | ((data: TData) => string);
  action?: { label: string; onClick: () => void };
  onSuccess?: (data: TData, variables: TVariables) => void;
  onError?: (error: Error, variables: TVariables) => void;
}) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: options.mutationFn,
    onSuccess: async (data, variables) => {
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
