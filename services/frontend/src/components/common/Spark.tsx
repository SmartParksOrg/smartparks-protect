/** A sparkline (decision D388): the shape of a week in a line the height of a text row, no
 * axes, in the current text colour. Nothing is drawn for fewer than two values. */
export function Spark({
  values,
  className = "h-5 w-16",
}: {
  values: number[];
  className?: string;
}) {
  const shown = values.filter((v) => Number.isFinite(v));
  if (shown.length < 2) return null;
  const min = Math.min(...shown);
  const max = Math.max(...shown);
  const span = max - min || 1;
  const width = 64;
  const height = 20;
  const points = shown
    .map((v, i) => {
      const x = (i / (shown.length - 1)) * (width - 2) + 1;
      const y = height - 2 - ((v - min) / span) * (height - 4);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
