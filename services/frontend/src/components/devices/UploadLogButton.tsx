import { useTranslation } from "react-i18next";
import { FileUp } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { LOG_FILE_ACCEPT, useLogFileUpload } from "@/hooks/useLogFileUpload";

/**
 * "Upload raw log" where people look for it (decision D367, Tim, 2026-11-06): the header of
 * the device page, the header of the entity page for the device it has now, and a row of the
 * Devices list. Several files at once; a station's card goes its own way (phase 42).
 */
export function UploadLogButton({
  deviceId,
  label,
  size = "sm",
  iconOnly = false,
  className,
}: {
  deviceId: string;
  /** The words on the button; "Upload raw log" by default. */
  label?: string;
  size?: "sm" | "icon";
  /** The icon alone, with the words as the title: a table row. */
  iconOnly?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const { uploadAll, isPending } = useLogFileUpload(deviceId);
  const words = label ?? t("Upload raw log");
  return (
    <>
      <input
        ref={input}
        type="file"
        multiple
        accept={LOG_FILE_ACCEPT}
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) void uploadAll(e.target.files);
          e.target.value = "";
        }}
      />
      <Button
        type="button"
        variant="outline"
        size={size}
        className={className}
        disabled={isPending}
        title={words}
        aria-label={words}
        onClick={(e) => {
          e.stopPropagation();
          input.current?.click();
        }}
      >
        <FileUp className="size-4" />
        {!iconOnly && (isPending ? t("Uploading…") : words)}
      </Button>
    </>
  );
}
