import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";

/** One editable name per selected device, for the dialogs that make an entity per device
 * (decision D294): the device's name is the usual entity name, so it is the default. */
export function NameRows({
  rows,
  names,
  onChange,
}: {
  rows: { id: string; name: string }[];
  names: Record<string, string>;
  onChange: (id: string, name: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="max-h-64 overflow-y-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="px-3 py-1.5 font-medium">{t("Device")}</th>
            <th className="px-3 py-1.5 font-medium">{t("Entity name")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b last:border-b-0">
              <td className="px-3 py-1 font-mono text-xs">{row.name}</td>
              <td className="px-3 py-1">
                <Input
                  className="h-8"
                  value={names[row.id] ?? row.name}
                  onChange={(e) => onChange(row.id, e.target.value)}
                  aria-label={t("Entity name for {{device}}", { device: row.name })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
