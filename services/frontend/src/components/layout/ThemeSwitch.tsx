import { useTranslation } from "react-i18next";
import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";

/** The light, dark or system switch in the top bar (decision D183): one button that cycles. */
export function ThemeSwitch() {
  const { t } = useTranslation();
  const { theme, cycle } = useTheme();
  const label =
    theme === "light"
      ? t("Light theme; press for dark")
      : theme === "dark"
        ? t("Dark theme; press to follow the device")
        : t("Theme follows the device; press for light");
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      title={label}
      onClick={cycle}
    >
      <Icon className="size-5" />
    </Button>
  );
}
