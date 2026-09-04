/**
 * Typed fetch wrapper. One place attaches the bearer token, parses errors into `ApiError`, and
 * tells the auth store when the server says 401 so the router can send the user to the login page
 * without a full reload. Paths are relative to the API origin (`VITE_API_URL`, empty for same
 * origin), so the same build works behind nginx and behind the Vite dev proxy.
 */
import { useAuthStore } from "@/stores/auth";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? ApiError.describe(status, detail));
    this.status = status;
    this.detail = detail;
  }

  static describe(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
    return `Request failed with status ${status}`;
  }
}

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

async function errorDetail(response: Response): Promise<unknown> {
  try {
    return ((await response.json()) as { detail?: unknown }).detail ?? null;
  } catch {
    return response.text().catch(() => null);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: Record<string, string>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Skip the 401 handling, for the login call itself. */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: Query): string {
  const url = new URL(BASE + path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  const token = useAuthStore.getState().token;
  if (token && !options.anonymous) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams(options.form).toString();
  } else if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(buildUrl(path, options.query), { method, headers, body, signal: options.signal });
  if (response.status === 401 && !options.anonymous) {
    useAuthStore.getState().expire();
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response));
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.arrayBuffer()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, options?: RequestOptions) => request<T>("POST", path, options),
  put: <T>(path: string, options?: RequestOptions) => request<T>("PUT", path, options),
  patch: <T>(path: string, options?: RequestOptions) => request<T>("PATCH", path, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};

/** WebSocket URL for a project stream, same origin as the API. */
export function wsUrl(projectId: string, token: string): string {
  const base = new URL(BASE || window.location.origin, window.location.origin);
  const protocol = base.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${base.host}/api/v1/ws/projects/${projectId}?token=${encodeURIComponent(token)}`;
}

/** Download a file that needs the bearer token: fetch it, then hand the browser a blob link. */
export async function downloadFile(path: string, fallbackName: string, query?: Query): Promise<void> {
  const token = useAuthStore.getState().token;
  const response = await fetch(buildUrl(path, query), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
