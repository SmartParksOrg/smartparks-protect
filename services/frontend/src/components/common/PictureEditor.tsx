import { useTranslation } from "react-i18next";
import { Camera, X } from "lucide-react";
import { type ReactNode, useRef } from "react";

import { api } from "@/api/client";
import { ObjectPicture } from "@/components/common/ObjectPicture";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";

/** The profile picture in a page header (decision D110): the picture or the type icon, and
 * for people who may edit the object a camera button that picks a file and a cross that
 * removes the picture. The server keeps a small square, so any phone photo will do. */
export function PictureEditor({
  path,
  updatedAt,
  name,
  fallback,
  editable,
  invalidate,
}: {
  path: string;
  updatedAt: string | null | undefined;
  name: string;
  fallback: ReactNode;
  editable: boolean;
  invalidate: (readonly unknown[])[];
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement | null>(null);
  const upload = useMutationToast({
    mutationFn: (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return api.put<unknown>(path, { body });
    },
    invalidate,
    success: t("Picture updated"),
  });
  const remove = useMutationToast({
    mutationFn: () => api.delete<unknown>(path),
    invalidate,
    success: t("Picture removed"),
  });
  return (
    <div className="relative shrink-0">
      <ObjectPicture
        path={path}
        updatedAt={updatedAt}
        name={name}
        size="lg"
        fallback={
          <span className="flex size-12 items-center justify-center rounded-full border border-dashed text-primary">
            {fallback}
          </span>
        }
      />
      {editable && (
        <>
          <input
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
              e.target.value = "";
            }}
          />
          <Button
            type="button"
            variant="secondary"
            size="icon"
            className="absolute -bottom-1 -right-1 size-6 rounded-full shadow"
            aria-label={updatedAt ? t("Change the picture") : t("Set a picture")}
            title={updatedAt ? t("Change the picture") : t("Set a picture")}
            disabled={upload.isPending}
            onClick={() => input.current?.click()}
          >
            <Camera className="size-3.5" />
          </Button>
          {updatedAt && (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              className="absolute -right-1 -top-1 size-5 rounded-full shadow"
              aria-label={t("Remove the picture")}
              title={t("Remove the picture")}
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              <X className="size-3" />
            </Button>
          )}
        </>
      )}
    </div>
  );
}
