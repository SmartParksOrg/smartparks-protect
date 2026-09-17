import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import App from "@/App";
import i18n from "@/i18n";
import { Toaster } from "@/components/ui/sonner";
import "@/index.css";
import { reloadOnStaleChunk } from "@/lib/staleChunk";

reloadOnStaleChunk();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30 * 1000, refetchOnWindowFocus: false, retry: 1 },
  },
});
// the server answers in the chosen language, so a change refetches what is on screen
i18n.on("languageChanged", () => void queryClient.invalidateQueries());

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root is missing from index.html");
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <Toaster position="top-right" richColors />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
