/**
 * Authentication state. The token lives here (and in localStorage so a reload keeps the session);
 * everything that needs it reads this store. `expire()` is called by the API client on a 401; the
 * router reacts by showing the login page with a return path. No `window.location` anywhere.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api } from "@/api/client";
import type { User } from "@/api/types";

interface AuthState {
  token: string | null;
  user: User | null;
  status: "anonymous" | "loading" | "authenticated" | "expired";
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  expire: () => void;
  loadMe: () => Promise<void>;
  setToken: (token: string) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      status: "anonymous",
      async login(email, password) {
        const response = await api.post<{ access_token: string }>("/api/v1/auth/login", {
          form: { username: email, password },
          anonymous: true,
        });
        set({ token: response.access_token, status: "loading" });
        await get().loadMe();
      },
      logout() {
        set({ token: null, user: null, status: "anonymous" });
      },
      expire() {
        if (get().token) set({ token: null, user: null, status: "expired" });
      },
      async loadMe() {
        if (!get().token) {
          set({ user: null, status: "anonymous" });
          return;
        }
        set({ status: "loading" });
        try {
          const user = await api.get<User>("/api/v1/users/me");
          set({ user, status: "authenticated" });
        } catch {
          set({ token: null, user: null, status: "expired" });
        }
      },
      setToken(token) {
        set({ token });
      },
    }),
    { name: "protect-auth", partialize: (state) => ({ token: state.token }) },
  ),
);

export const isServerAdmin = (user: User | null): boolean => Boolean(user?.is_superuser);
