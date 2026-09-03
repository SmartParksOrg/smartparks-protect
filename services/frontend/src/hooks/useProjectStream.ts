import { useEffect, useRef } from "react";

import { wsUrl } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

export interface StreamMessage {
  topic: string;
  [key: string]: unknown;
}

/** Live updates for a project over WebSocket with reconnect. */
export function useProjectStream(projectId: string | undefined, onMessage: (message: StreamMessage) => void) {
  const token = useAuthStore((s) => s.token);
  const handler = useRef(onMessage);
  useEffect(() => {
    handler.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    if (!projectId || !token) return;
    let socket: WebSocket | null = null;
    let closed = false;
    let retry = 1000;
    const connect = () => {
      socket = new WebSocket(wsUrl(projectId, token));
      socket.onmessage = (event) => {
        try {
          handler.current(JSON.parse(event.data as string) as StreamMessage);
        } catch {
          // ignore malformed frames
        }
      };
      socket.onopen = () => (retry = 1000);
      socket.onclose = () => {
        if (closed) return;
        setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      };
    };
    connect();
    return () => {
      closed = true;
      socket?.close();
    };
  }, [projectId, token]);
}
