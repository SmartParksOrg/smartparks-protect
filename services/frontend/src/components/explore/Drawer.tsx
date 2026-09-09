import { ChevronDown, ChevronUp } from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { drawerSpace, HANDLE } from "@/components/explore/drawer";
import { Button } from "@/components/ui/button";

const MIN_HEIGHT = 120;
/**
 * The drawer at the bottom of the Explore canvas (decision D151): the records table under the
 * chart or the map, pulled up by its handle to the height a person likes (kept per user) and
 * folded to the handle alone. On a phone it opens to a fixed share of the screen.
 */
export function Drawer({
  height,
  onHeight,
  open,
  onOpen,
  phone,
  bar,
  children,
}: {
  height: number;
  onHeight: (height: number) => void;
  open: boolean;
  onOpen: (open: boolean) => void;
  phone: boolean;
  /** What the handle shows: the progress row. */
  bar: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [dragging, setDragging] = useState<number | null>(null);
  const element = useRef<HTMLDivElement | null>(null);
  const shown = dragging ?? height;

  function startDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (phone || (event.target as HTMLElement).closest("button")) return;
    const parent = element.current?.parentElement;
    if (!parent) return;
    const rect = parent.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (e: PointerEvent) => {
      const next = Math.round(
        Math.min(
          rect.height - 80,
          Math.max(MIN_HEIGHT, rect.bottom - e.clientY),
        ),
      );
      setDragging(next);
    };
    const up = (e: PointerEvent) => {
      const next = Math.round(
        Math.min(
          rect.height - 80,
          Math.max(MIN_HEIGHT, rect.bottom - e.clientY),
        ),
      );
      setDragging(null);
      onHeight(next);
      if (!open) onOpen(true);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  return (
    <div
      ref={element}
      className="absolute right-0 bottom-0 left-0 z-20 flex flex-col border-t bg-card shadow-[0_-4px_12px_rgba(0,0,0,0.08)]"
      style={{
        height: drawerSpace(open, shown, phone),
        transition: dragging === null ? "height 120ms ease-out" : undefined,
      }}
    >
      <div
        className={`flex shrink-0 items-center gap-3 px-3 text-sm ${phone ? "" : "cursor-row-resize"}`}
        style={{ height: HANDLE }}
        onPointerDown={startDrag}
        onDoubleClick={() => onOpen(!open)}
      >
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={open ? t("Fold the table") : t("Unfold the table")}
          aria-expanded={open}
          onClick={() => onOpen(!open)}
        >
          {open ? (
            <ChevronDown className="size-4" />
          ) : (
            <ChevronUp className="size-4" />
          )}
        </Button>
        <div className="flex min-w-0 flex-1 items-center gap-3">{bar}</div>
      </div>
      {open && <div className="relative min-h-0 flex-1">{children}</div>}
    </div>
  );
}
