import { useTranslation } from "react-i18next";

import {
  type FenceMonitor,
  type FenceSection,
  fenceColor,
  fenceLevelLabel,
  kilovolts,
} from "@/lib/fence";
import { formatLength } from "@/lib/geodesy";

/**
 * A fence line as one bar (Tim, 2026-09-19): the line from its start to its end, each
 * section in its level's colour, a tick where each monitor stands. Reads in a second on a
 * phone, and a long fence with many sections stays one bar. With `labels` the monitors are
 * named under their ticks, for the page.
 */
export function FenceStrip({
  lengthM,
  sections,
  monitors,
  labels = false,
  className,
}: {
  lengthM: number;
  sections: FenceSection[];
  monitors: FenceMonitor[];
  labels?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const width = 1000;
  const bar = labels ? 22 : 12;
  const height = labels ? 58 : 20;
  const x = (m: number) => (lengthM > 0 ? (m / lengthM) * width : 0);
  const name = (id: string) =>
    monitors.find((m) => m.entity_id === id)?.name ?? "?";
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className ?? "h-5 w-full"}
      role="img"
      aria-label={t("The fence line, section by section")}
    >
      {sections.map((s, i) => (
        <rect
          key={i}
          x={x(s.from_m)}
          y={4}
          width={Math.max(2, x(s.to_m) - x(s.from_m))}
          height={bar}
          fill={fenceColor(s.level)}
          rx={2}
        >
          <title>
            {`${formatLength(s.from_m)} – ${formatLength(s.to_m)}: ${fenceLevelLabel(s.level, t)}${
              s.monitor_ids?.length
                ? ` (${s.monitor_ids.map(name).join(" · ")})`
                : ""
            }`}
          </title>
        </rect>
      ))}
      {monitors
        .filter((m) => m.position_m != null)
        .map((m) => (
          <g key={m.entity_id}>
            <rect
              x={x(m.position_m as number) - 3}
              y={1}
              width={6}
              height={bar + 6}
              fill="#ffffff"
              stroke={fenceColor(m.level)}
              strokeWidth={2}
              rx={1}
              vectorEffect="non-scaling-stroke"
            >
              <title>{`${m.name}: ${kilovolts(m.voltage_v)}, ${fenceLevelLabel(m.level, t)}`}</title>
            </rect>
            {labels && (
              <text
                x={x(m.position_m as number)}
                y={bar + 22}
                textAnchor="middle"
                fontSize={11}
                fill="currentColor"
                style={{ fontFamily: "inherit" }}
              >
                {m.name}
              </text>
            )}
          </g>
        ))}
    </svg>
  );
}
