import type { ChartGroup } from "@/lib/explore";

/** The look of the Explore chart (decision D152): the palette and the lines it draws. */
/** Brand palette first, then muted variants; one colour per series. */
export const PALETTE = [
  "#52735E",
  "#D9825F",
  "#5C7FA3",
  "#B39A4A",
  "#8A6BA3",
  "#B86B5C",
  "#3E8E7E",
  "#8A7A4F",
  "#3E5A48",
  "#C48A9E",
];
export const MARK = "#B86B5C";
export const TEXT = "#6B7280";
export const GRID = "#E5E7EB";

export interface ChartLine {
  key: string;
  name: string;
  colour: string;
  group: ChartGroup;
  data: number[][];
}

/** One line per metric and owner, in a stable order with a stable colour. */
export function chartLines(groups: ChartGroup[]): ChartLine[] {
  const many = groups.some((g) => g.series.length > 1);
  const lines: ChartLine[] = [];
  for (const g of groups)
    for (const s of g.series)
      lines.push({
        key: `${g.metric}|${s.ownerId}`,
        name:
          groups.length === 1
            ? s.name
            : many
              ? `${g.label} · ${s.name}`
              : g.label,
        colour: PALETTE[lines.length % PALETTE.length],
        group: g,
        data: s.data,
      });
  return lines;
}
