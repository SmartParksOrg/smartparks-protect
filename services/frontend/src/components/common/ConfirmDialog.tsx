import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Every destructive action asks first. */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", destructive = true, onConfirm, pending }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; description?: ReactNode; confirmLabel?: string; destructive?: boolean; onConfirm: () => void; pending?: boolean }) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t("Cancel")}</Button>
          <Button variant={destructive ? "destructive" : "default"} onClick={onConfirm} disabled={pending}>{pending ? "Working…" : confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
