import { useTranslation } from "react-i18next";

/** What the movement method cannot say (plan, section 8.10), folded under the results and
 * unfolded on paper. */
export function MovementLimitations() {
  const { t } = useTranslation();
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("What these figures can and cannot say")}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
        <li>
          {t(
            "Distance from fixes underestimates the path between them; a coarser sampling means a shorter apparent distance. The sampling interval stands next to the distance for that reason.",
          )}
        </li>
        <li>
          {t("Speed is the mean over a step, not an instantaneous speed.")}
        </li>
        <li>
          {t(
            "The KDE is an estimate of space use that depends on the bandwidth and the grid; its isopleths are unions of cells, not smooth contours.",
          )}
        </li>
        <li>{t("The MCP includes ground never visited between far fixes.")}</li>
        <li>
          {t(
            "Residence time on a regular grid depends on the cell size and is biased by irregular sampling.",
          )}
        </li>
        <li>
          {t(
            "Day and night follow the sun's elevation, not the animal's own rhythm or the cloud cover.",
          )}
        </li>
        <li>
          {t("The results describe the collared animals, not the population.")}
        </li>
      </ul>
    </details>
  );
}

/** What the grazing figures cannot say (plan, section 9.6), folded under the results. */
export function GrazingLimitations() {
  const { t } = useTranslation();
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("What these figures can and cannot say")}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
        <li>
          {t(
            "Time in an area is a proxy for potential grazing pressure, not measured feeding; the tables say use, not grazing.",
          )}
        </li>
        <li>
          {t(
            "Only collared animals count; the herd is not extrapolated unless a weighting is chosen, and then the document names it.",
          )}
        </li>
        <li>
          {t(
            "Fix sampling and gaps bias the hours; the missing fix share and the gaps are in the warnings next to the totals.",
          )}
        </li>
        <li>
          {t(
            "Overlapping areas double-count by design; the overlap is listed.",
          )}
        </li>
        <li>
          {t(
            "Areas are fixed polygons without validity in time; an area that changed during the period must be two features.",
          )}
        </li>
      </ul>
    </details>
  );
}

/** What the device performance figures cannot say (plan, section 10). */
export function DevicePerformanceLimitations() {
  const { t } = useTranslation();
  return (
    <details className="rounded-md border px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium">
        {t("What these figures can and cannot say")}
      </summary>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
        <li>
          {t(
            "A missed report is inferred from the device's settings and its messages; a device whose interval changed in the period, or whose settings Protect never read, shows a share to weigh, with the interval it assumed beside it.",
          )}
        </li>
        <li>
          {t(
            "Lost uplinks come from the frame counter; a data source that does not deliver it shows no figure, not zero.",
          )}
        </li>
        <li>
          {t(
            "The battery slope is a straight line through the daily medians; a battery's curve is not straight, so the days to critical are an indication, not a forecast.",
          )}
        </li>
        <li>
          {t(
            "Signal figures are the best gateway's per uplink; a moving device changes gateways, so they describe the network as the device met it.",
          )}
        </li>
        <li>
          {t(
            "Levels come from the driver's thresholds and named defaults; they are not a verdict on the device, and a rank says only where a device stands among the chosen ones.",
          )}
        </li>
        <li>
          {t(
            "Fix success counts the attempts the device reported; a device that never reports a failed attempt shows every attempt as a fix.",
          )}
        </li>
      </ul>
    </details>
  );
}
