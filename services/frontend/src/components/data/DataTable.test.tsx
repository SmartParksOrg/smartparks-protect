import { act, render } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";

import { DataTable } from "@/components/data/DataTable";

type Row = { name: string };

let headerRenders = 0;
const columns: ColumnDef<Row, unknown>[] = [
  {
    accessorKey: "name",
    header: () => {
      headerRenders += 1;
      return "Name";
    },
  },
];

beforeAll(() => {
  // jsdom has no matchMedia; the table asks it for the phone breakpoint
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }) as unknown as MediaQueryList;
});

describe("DataTable", () => {
  it("settles while its rows are not loaded yet", async () => {
    // the Offload page's files section (Tim, 2026-10-18): a device change made the rows
    // undefined again while the table was mounted, and every render then made a new empty
    // array, which TanStack Table answered with a page index reset, which rendered again
    const { rerender } = render(
      <DataTable<Row> columns={columns} data={undefined} isLoading />,
    );
    await act(async () => {});
    headerRenders = 0;
    rerender(<DataTable<Row> columns={columns} data={undefined} isLoading />);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(headerRenders).toBeLessThan(5);
  });
});
