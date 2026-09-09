import { useTranslation } from "react-i18next";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatInZone } from "@/lib/analytics";

export interface SparkPoint {
  time: string;
  value: number;
}

/** A small line of one column over time (decision D146), drawn as SVG from the loaded rows;
 * the same drawing enlarges in a dialog. */
export function Sparkline({
  points,
  width = 160,
  height = 40,
  stroke = "#52735E",
}: {
  points: SparkPoint[];
  width?: number;
  height?: number;
  stroke?: string;
}) {
  if (points.length === 0) return <svg width={width} height={height} />;
  const times = points.map((p) => new Date(p.time).getTime());
  const values = points.map((p) => p.value);
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const v0 = Math.min(...values);
  const v1 = Math.max(...values);
  const x = (t: number) =>
    t1 === t0 ? width / 2 : ((t - t0) / (t1 - t0)) * (width - 2) + 1;
  const y = (v: number) =>
    v1 === v0 ? height / 2 : height - 1 - ((v - v0) / (v1 - v0)) * (height - 2);
  const d = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${x(times[i]).toFixed(1)},${y(p.value).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
    >
      <path
        d={d}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function SparklineDialog({
  title,
  unit,
  points,
  timezone,
  onClose,
}: {
  title: string | null;
  unit?: string | null;
  points: SparkPoint[];
  timezone: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const values = points.map((p) => p.value);
  const min = values.length ? Math.min(...values) : null;
  const max = values.length ? Math.max(...values) : null;
  return (
    <Dialog open={title !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {title}
            {unit ? ` (${unit})` : ""}
          </DialogTitle>
          <DialogDescription>
            {points.length > 0
              ? t(
                  "{{count}} values from {{from}} to {{to}}, {{min}} to {{max}}",
                  {
                    count: points.length,
                    from: formatInZone(points[0].time, timezone),
                    to: formatInZone(points[points.length - 1].time, timezone),
                    min: min?.toFixed(2),
                    max: max?.toFixed(2),
                  },
                )
              : t("No numeric values in the loaded rows.")}
          </DialogDescription>
        </DialogHeader>
        <div className="overflow-x-auto">
          <Sparkline points={points} width={720} height={240} />
        </div>
      </DialogContent>
    </Dialog>
  );
}
