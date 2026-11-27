import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Info, Minus } from "lucide-react";
import { useState } from "react";

import { Callout } from "@/components/common/Callout";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type {
  FieldRow,
  GroupRow,
  MatrixRow,
  PanelView,
  Row,
} from "@/lib/settingsPanels";
import { cn } from "@/lib/utils";

/**
 * A device's settings by topic (decision D432): the guided panels of the Smart Parks settings
 * app, read against what Protect knows. A topic is one line with its sentence; a click opens
 * its settings in plain words, one topic at a time. The texts of the panels are the app's own
 * and stay English (phase 50, "Not in this phase").
 */
export function SettingsPanels({ views }: { views: PanelView[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="rounded-md border">
      {views.map((view) => {
        const isOpen = open === view.id;
        return (
          <div key={view.id} className="border-t first:border-t-0">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : view.id)}
              className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-muted/40"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {view.title}
                  {view.beta && <Badge variant="outline">{t("beta")}</Badge>}
                </div>
                <div className="text-sm text-muted-foreground">
                  {view.summary ||
                    (view.known === 0
                      ? t("Not known yet")
                      : view.known < view.total
                        ? t("{{known}} of {{total}} settings known", {
                            known: view.known,
                            total: view.total,
                          })
                        : view.description)}
                </div>
              </div>
              <ChevronDown
                className={cn(
                  "mt-1 size-4 shrink-0 text-muted-foreground transition-transform",
                  isOpen && "rotate-180",
                )}
              />
            </button>
            {isOpen && (
              <div className="space-y-3 border-t bg-muted/20 px-3 py-3">
                {view.summary && view.description && (
                  <p className="text-xs text-muted-foreground">
                    {view.description}
                  </p>
                )}
                <Rows rows={view.rows} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Rows({ rows }: { rows: Row[] }) {
  return (
    <div className="space-y-3">
      {rows.map((row) =>
        row.kind === "group" ? (
          <Group key={row.id} group={row} />
        ) : row.kind === "matrix" ? (
          <Matrix key={row.id} matrix={row} />
        ) : (
          <Field key={row.id} row={row} />
        ),
      )}
    </div>
  );
}

function Help({ label, text }: { label: string; text: string }) {
  const { t } = useTranslation();
  if (!text) return null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("About {{name}}", { name: label })}
          className="rounded-full p-0.5 text-muted-foreground hover:text-foreground"
        >
          <Info className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="max-w-xs text-sm">{text}</PopoverContent>
    </Popover>
  );
}

function Field({ row }: { row: FieldRow }) {
  const { t } = useTranslation();
  return (
    <div>
      <div
        className={cn(
          "grid grid-cols-1 gap-x-4 gap-y-0.5 text-sm sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]",
          row.inactive && "text-muted-foreground",
        )}
      >
        <div className="flex items-center gap-1.5">
          <span title={row.keys.join(", ")}>{row.label}</span>
          <Help label={row.label} text={row.help} />
        </div>
        <div
          className={cn(
            "break-words tabular-nums",
            !row.inactive && row.value !== null && "font-medium",
          )}
        >
          {row.value ?? (
            <span className="text-muted-foreground">{t("unknown")}</span>
          )}
        </div>
      </div>
      {row.inactive && row.reason && (
        <p className="text-xs text-muted-foreground">{row.reason}</p>
      )}
      {row.warnings.map((warning) => (
        <Callout key={warning} kind="warning" className="mt-1">
          {warning}
        </Callout>
      ))}
    </div>
  );
}

function Group({ group }: { group: GroupRow }) {
  const body = (
    <div className="space-y-3 pt-2">
      {group.summary && <p className="text-sm">{group.summary}</p>}
      {group.help && (
        <p className="text-xs text-muted-foreground">{group.help}</p>
      )}
      <Rows rows={group.rows} />
    </div>
  );
  if (group.advanced)
    return (
      <details className="rounded-md border bg-background px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium">
          {group.title}
        </summary>
        {body}
      </details>
    );
  return (
    <div className="rounded-md border bg-background px-3 py-2">
      <div className="text-sm font-medium">{group.title}</div>
      {body}
    </div>
  );
}

function Matrix({ matrix }: { matrix: MatrixRow }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto rounded-md border bg-background">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-xs">
            <th className="px-3 py-1.5 text-left font-medium">
              {matrix.label}
            </th>
            {matrix.columns.map((column) => (
              <th key={column.key} className="px-2 py-1.5 font-medium">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.ports.map((port) => (
            <tr key={port.number} className="border-t first:border-t-0">
              <td className="px-3 py-1">
                {port.label}{" "}
                <span className="text-xs text-muted-foreground">
                  {t("port {{n}}", { n: port.number })}
                </span>
              </td>
              {port.set.map((set, index) => (
                <td key={matrix.columns[index].key} className="px-2 py-1">
                  {!matrix.columns[index].known ? (
                    <span className="block text-center text-xs text-muted-foreground">
                      ?
                    </span>
                  ) : set ? (
                    <Check
                      className="mx-auto size-4 text-primary"
                      aria-label={t("yes")}
                    />
                  ) : (
                    <Minus
                      className="mx-auto size-3 text-muted-foreground/50"
                      aria-label={t("no")}
                    />
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
