import { useCountUp } from "@/lib/motion";

/** A summary number that counts to its value (decision D383): from zero when it first appears,
 * from the number shown before when a live update changes it, 400 ms; the value at once under
 * reduce motion. The caller formats the number as it did before. */
export function CountUp({
  value,
  format,
  className,
}: {
  value: number | null;
  format: (value: number | null) => string;
  className?: string;
}) {
  const shown = useCountUp(value);
  return <span className={className}>{format(shown)}</span>;
}
