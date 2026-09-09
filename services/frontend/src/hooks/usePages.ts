import {
  keepPreviousData,
  type QueryKey,
  useInfiniteQuery,
} from "@tanstack/react-query";
import { useMemo } from "react";

import type { Page } from "@/api/types";

/**
 * A list read page after page (decision D149): the first page at once, the next on "Load
 * more", every page kept in the query cache. Replaces the "only the first 500 rows are shown"
 * walls: the bound per request stays, the person reaches every row.
 */
export function usePages<T>({
  queryKey,
  fetchPage,
  enabled = true,
  keepPrevious = false,
}: {
  queryKey: QueryKey;
  fetchPage: (cursor: string | undefined) => Promise<Page<T>>;
  enabled?: boolean;
  keepPrevious?: boolean;
}) {
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
  const items = useMemo(
    () => query.data?.pages.flatMap((p) => p.items) ?? [],
    [query.data],
  );
  return {
    items,
    loaded: query.data !== undefined,
    isPending: query.isPending,
    hasMore: query.hasNextPage,
    isLoadingMore: query.isFetchingNextPage,
    loadMore: () => void query.fetchNextPage(),
    refetch: () => void query.refetch(),
  };
}
