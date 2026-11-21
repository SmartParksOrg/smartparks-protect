import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("finds a code typed with other spacing than it is stored with", async () => {
    // an ear tag is stored without spaces and typed with them (decision D406)
    const rows = [
      "Cow 01 NL100020003001",
      "Cow 02 NL100020003002",
      ...Array.from({ length: 6 }, (_, i) => `Goat ${i}`),
    ].map((name) => ({ name }));
    render(<DataTable<Row> columns={columns} data={rows} searchable />);
    fireEvent.change(screen.getAllByPlaceholderText("Search this list")[0]!, {
      target: { value: "nl 1000 2000 3002" },
    });
    await act(async () => {});
    expect(screen.queryAllByText(/Cow 02/).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/Cow 01/)).toHaveLength(0);
    expect(screen.queryAllByText(/Goat/)).toHaveLength(0);
  });
});
