import { usePreference } from "@/hooks/usePreference";
import { useAuthStore } from "@/stores/auth";

/** Whether this person wants the machinery shown (decision D105): identities, ports, traces,
 * provider fields and the Network section. Server admins start with it on, everyone else off;
 * the choice is kept per user. */
export function useTechnicalDetails(): [boolean, (on: boolean) => void] {
  const superuser = useAuthStore((s) => Boolean(s.user?.is_superuser));
  return usePreference<boolean>("technical_details", superuser);
}
