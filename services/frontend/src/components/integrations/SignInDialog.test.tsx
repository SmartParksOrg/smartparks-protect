import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import { SignInDialog } from "@/components/integrations/SignInDialog";

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <SignInDialog
        projectId="p1"
        integrationId="i1"
        target="Target"
        defaultEmail="tim@example.org"
        invalidate={[]}
        open
        onOpenChange={() => {}}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("SignInDialog", () => {
  it("asks for a code, then signs in with it and says what the account may do", async () => {
    const post = vi
      .spyOn(api, "post")
      .mockImplementation(async (path: string) => {
        if (path.endsWith("/login/code")) return undefined;
        if (path.endsWith("/login"))
          return { account: "tim@example.org", scopes: ["data-system"] };
        return {
          ok: true,
          detail: "accepted",
          response: { roles: ["data-system"], can_register_animals: false },
        };
      });
    show();
    expect(screen.getByLabelText("Email address of the account")).toHaveValue(
      "tim@example.org",
    );
    fireEvent.click(screen.getByRole("button", { name: "Send me a code" }));
    expect(
      await screen.findByText("A code is on its way to tim@example.org."),
    ).toBeInTheDocument();
    expect(post.mock.calls[0]![1]).toEqual({
      body: { email: "tim@example.org" },
    });

    const signIn = screen.getByRole("button", { name: "Sign in" });
    expect(signIn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Code from the email"), {
      target: { value: " 123456 " },
    });
    fireEvent.click(signIn);
    expect(
      await screen.findByText(/Signed in as tim@example.org\./),
    ).toBeInTheDocument();
    expect(post.mock.calls[1]![1]).toEqual({
      body: { email: "tim@example.org", code: "123456" },
    });
    expect(
      screen.getByText("Roles on Target: data-system"),
    ).toBeInTheDocument();
    // the account may send data but not register entities: said, not hidden
    expect(
      screen.getByText(/may send data but not register/),
    ).toBeInTheDocument();
  });

  it("shows what the target answered for a wrong code and lets the person try again", async () => {
    vi.spyOn(api, "post").mockImplementation(async (path: string) => {
      if (path.endsWith("/login/code")) return undefined;
      throw new Error("The target did not accept the code.");
    });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Send me a code" }));
    fireEvent.change(await screen.findByLabelText("Code from the email"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByText("The target did not accept the code."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Send a new code" }),
      ).toBeEnabled(),
    );
  });
});
