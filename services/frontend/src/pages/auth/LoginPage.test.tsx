import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import { LoginPage } from "@/pages/auth/LoginPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  it("shows the API version when the API answers", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ version: "v0.1.0", commit: "abc1234" }), { headers: { "content-type": "application/json" } })));
    renderPage();
    expect(screen.getByText("Smart Parks Protect")).toBeInTheDocument();
    expect(await screen.findByText("API v0.1.0 (abc1234)")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("says when the API is not reachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 503 })));
    renderPage();
    expect(await screen.findByText("API not reachable")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});
