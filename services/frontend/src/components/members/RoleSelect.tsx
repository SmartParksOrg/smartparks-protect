import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { queryKeys } from "@/api/queryKeys";
import type { ProjectRole } from "@/api/types";
import { CUSTOM } from "@/components/members/roles";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BUILTIN_ROLES, roleLabel } from "@/lib/permissions";

/** A role select for one project: the built-in roles and, once a project is known, its custom
 * roles (the value is a built-in key or `custom:<id>`, see `roles.ts`). */
export function RoleSelect({
  id,
  projectId,
  value,
  onChange,
  className,
}: {
  id?: string;
  projectId: string | null;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  const roles = useQuery({
    queryKey: queryKeys.roles(projectId ?? ""),
    queryFn: () =>
      api.get<ProjectRole[]>(`/api/v1/projects/${projectId}/roles`),
    enabled: !!projectId,
  });
  const options = [
    ...BUILTIN_ROLES.map((r) => ({ value: r, label: roleLabel(r) })),
    ...(roles.data ?? []).map((r) => ({
      value: `${CUSTOM}${r.id}`,
      label: r.name,
    })),
  ];
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        id={id}
        className={className ?? "w-44"}
        aria-label={t("Role")}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
