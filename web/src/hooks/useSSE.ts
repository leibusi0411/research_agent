import { useCallback, useEffect, useRef, useState } from "react";
import { type ProgressEvent, subscribeTaskEvents } from "../api";

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export function useSSE(
  taskId: string | null,
  onEvent: (event: ProgressEvent) => void,
  onResult: () => void,
  onError: () => void,
) {
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const closeRef = useRef<() => void>(() => {});

  // R-84: Store callbacks in refs to avoid stale closures without
  // re-triggering the SSE subscription when callbacks change.
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const startSSE = useCallback((id: string) => {
    const unsubscribe = subscribeTaskEvents(
      id,
      (event) => {
        setConnectionState("connected");
        onEventRef.current(event);
      },
      () => {
        setConnectionState("disconnected");
        onResultRef.current();
      },
      () => {
        setConnectionState("disconnected");
        onErrorRef.current();
      },
    );

    closeRef.current = () => {
      unsubscribe();
      setConnectionState("disconnected");
    };

    return unsubscribe;
  }, []);

  useEffect(() => {
    if (!taskId) {
      setConnectionState("disconnected");
      return;
    }

    setConnectionState("connected");
    const unsubscribe = startSSE(taskId);

    return () => {
      unsubscribe();
    };
  }, [taskId, startSSE]);

  return { connectionState, close: () => closeRef.current() };
}
