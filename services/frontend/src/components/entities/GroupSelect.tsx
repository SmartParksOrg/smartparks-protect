import { useTranslation } from "react-i18next";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { groupTree, UNGROUPED, useGroups } from "@/hooks/useGroups";

/** A group choice (decision D98). `mode` "filter" offers every group and "Ungrouped"; "choice"
 * offers "No group". The value is the group id, the ungrouped marker, or "" for all or none. */
export function GroupSelect({
  projectId,
  value,
  onChange,
  mode,
  id,
  disabled,
  className,
}: {
  projectId: string | undefined;
  value: string;
  onChange: (value: string) => void;
  mode: "filter" | "choice";
  id?: string;
  disabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const groups = useGroups(projectId);
  const rows = groupTree(groups.data);
  if (mode === "filter" && rows.length === 0) return null;
  return (
    <Select
      value={value || "all"}
      onValueChange={(v) => onChange(v === "all" ? "" : v)}
      disabled={disabled}
    >
      <SelectTrigger id={id} className={className} aria-label={t("Group")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">
          {mode === "filter" ? t("All groups") : t("No group")}
        </SelectItem>
        {mode === "filter" && (
          <SelectItem value={UNGROUPED}>{t("Ungrouped")}</SelectItem>
        )}
        {rows.map(({ group, depth }) => (
          <SelectItem key={group.id} value={group.id}>
            <span
              className="inline-flex items-center gap-2"
              style={{ paddingLeft: depth * 12 }}
            >
              {group.color && (
                <span
                  className="inline-block size-2.5 rounded-full"
                  style={{ background: group.color }}
                />
              )}
              {group.name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
