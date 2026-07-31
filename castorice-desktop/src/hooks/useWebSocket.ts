import { useEffect, useRef, useCallback, useState } from "react";
import api from "@/services/api";
import type { WSIncomingMessage, WSOutgoingMessage } from "@/types";

interface UseWebSocketOptions {
  onMessage?: (msg: WSIncomingMessage) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
  onError?: (err: Error) => void;
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    onMessage,
    onConnected,
    onDisconnected,
    onError,
    autoReconnect = true,
    reconnectInterval = 3000,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const manualCloseRef = useRef(false);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || isConnecting) return;

    setIsConnecting(true);
    manualCloseRef.current = false;

    try {
      const ws = new WebSocket(api.wsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setIsConnecting(false);
        onConnected?.();
        ws.send(JSON.stringify({ type: "auth", payload: { api_key: "" } }));
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSIncomingMessage = JSON.parse(event.data);
          onMessage?.(msg);
        } catch (e) {
          console.error("WS parse error:", e);
        }
      };

      ws.onerror = (e) => {
        console.error("WS error:", e);
        onError?.(new Error("WebSocket error"));
      };

      ws.onclose = () => {
        setIsConnected(false);
        setIsConnecting(false);
        onDisconnected?.();
        if (autoReconnect && !manualCloseRef.current) {
          reconnectTimerRef.current = window.setTimeout(() => {
            connect();
          }, reconnectInterval);
        }
      };
    } catch (e) {
      setIsConnecting(false);
      console.error("WS connect failed:", e);
    }
  }, [autoReconnect, reconnectInterval, onConnected, onDisconnected, onError, onMessage, isConnecting]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
    setIsConnecting(false);
  }, []);

  const send = useCallback((msg: WSOutgoingMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
      return true;
    }
    return false;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return { isConnected, isConnecting, send, connect, disconnect };
}
