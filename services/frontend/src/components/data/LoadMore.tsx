import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/** The footer of a paged list (decision D149): how many rows are here, and the next page on a
 * click. Nothing when every row is loaded. */
export function LoadMore({
  count,
  hasMore,
  isLoading,
  onLoadMore,
}: {
  count: number;
  hasMore: boolean;
  isLoading: boolean;
  onLoadMore: () => void;
}) {
  const { t } = useTranslation();
  if (!hasMore) return null;
  return (
    <div className="flex items-center gap-3 text-xs text-muted-foreground">
      <span>{t("{{count}} rows shown", { count })}</span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7"
        onClick={onLoadMore}
        disabled={isLoading}
      >
        {isLoading ? t("Loading…") : t("Load more")}
      </Button>
    </div>
  );
}
