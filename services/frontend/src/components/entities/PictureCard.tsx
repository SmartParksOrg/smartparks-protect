import { useTranslation } from "react-i18next";
import { Camera, ImageOff, X } from "lucide-react";
import { useRef } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useMutationToast } from "@/hooks/useMutationToast";
import { usePicture } from "@/hooks/usePicture";

/** The entity's picture as a card of its own on the entity page (decision D194): the same
 * frame as the small map beside it, the server's 4:3 crop filling it on every screen. It is
 * not the entity's icon anywhere; the type icon stays. People who may edit the entity get a
 * camera button that picks a file and a cross that removes the picture. */
export function PictureCard({
  path,
  updatedAt,
  name,
  editable,
  invalidate,
}: {
  path: string;
  updatedAt: string | null | undefined;
  name: string;
  editable: boolean;
  invalidate: (readonly unknown[])[];
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement | null>(null);
  const url = usePicture(path, updatedAt);
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
    <div className="relative h-full min-h-56 overflow-hidden rounded-xl border shadow-sm">
      {url ? (
        <img
          src={url}
          alt={name}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-muted/40 text-sm text-muted-foreground">
          <ImageOff className="size-6" />
          {updatedAt ? t("Loading the picture…") : t("No picture yet")}
        </div>
      )}
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
          <div className="absolute right-2 top-2 flex gap-1">
            <Button
              type="button"
              variant="secondary"
              size="icon"
              className="size-8 rounded-full shadow"
              aria-label={
                updatedAt ? t("Change the picture") : t("Set a picture")
              }
              title={updatedAt ? t("Change the picture") : t("Set a picture")}
              disabled={upload.isPending}
              onClick={() => input.current?.click()}
            >
              <Camera className="size-4" />
            </Button>
            {updatedAt && (
              <Button
                type="button"
                variant="secondary"
                size="icon"
                className="size-8 rounded-full shadow"
                aria-label={t("Remove the picture")}
                title={t("Remove the picture")}
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                <X className="size-4" />
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
