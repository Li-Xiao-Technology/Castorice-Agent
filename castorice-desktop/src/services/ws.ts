import { useAppStore } from "@/stores/appStore";
import api from "./api";
import type { Thought, EmotionState, Notification } from "@/types";

let notifyFn: ((title: string, body: string) => void) | null = null;

export function setNotificationHandler(fn: (title: string, body: string) => void) {
  notifyFn = fn;
}

function notify(title: string, body: string) {
  if (notifyFn) {
    try {
      notifyFn(title, body);
    } catch (e) {
      console.warn("[WS] 通知发送失败", e);
    }
  }
  if ("Notification" in window) {
    if (Notification.permission === "granted") {
      new Notification(title, { body });
    } else if (Notification.permission !== "denied") {
      Notification.requestPermission().then((p) => {
        if (p === "granted") new Notification(title, { body });
      });
    }
  }
}

class WSService {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private connected = false;
  private manuallyClosed = false;

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.manuallyClosed = false;
    const url = api.wsUrl();
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.connected = true;
      console.log("[WS] 已连接");
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) {
        console.warn("[WS] 解析消息失败", e);
      }
    };

    this.ws.onerror = (e) => {
      console.warn("[WS] 错误", e);
    };

    this.ws.onclose = () => {
      this.connected = false;
      this.stopHeartbeat();
      console.log("[WS] 连接关闭");
      if (!this.manuallyClosed) {
        this.scheduleReconnect();
      }
    };
  }

  disconnect() {
    this.manuallyClosed = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private handleMessage(msg: { type: string; payload: any }) {
    const state = useAppStore.getState();
    const setEmotion = state.setEmotion;
    const addEmotionHistoryPoint = state.addEmotionHistoryPoint;
    const addThought = state.addThought;
    const addProactiveMessage = state.addProactiveMessage;
    const addNotification = state.addNotification;

    switch (msg.type) {
      case "thought": {
        const thought = msg.payload as Thought;
        if (thought && thought.id) {
          addThought(thought);
          if (thought.thought_type === "external" && thought.importance > 0.6) {
            notify("Agent 有话想说", thought.content.slice(0, 120));
            addProactiveMessage({
              id: thought.id,
              content: thought.content,
              timestamp: thought.timestamp,
            });
            const notif: Notification = {
              id: thought.id,
              title: "Agent 有话想说",
              body: thought.content,
              timestamp: thought.timestamp,
              read: false,
              type: "thought",
            };
            addNotification(notif);
          }
        }
        break;
      }
      case "emotion": {
        const emotion = msg.payload as EmotionState;
        if (emotion) {
          setEmotion(emotion);
          addEmotionHistoryPoint({
            timestamp: Date.now(),
            pleasure: emotion.pleasure,
            arousal: emotion.arousal,
            dominance: emotion.dominance,
          });
        }
        break;
      }
      case "notification": {
        const title = msg.payload?.title || "Castorice";
        const body = msg.payload?.body || "";
        notify(title, body);
        const notif: Notification = {
          id: `notif_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          title,
          body,
          timestamp: new Date().toISOString(),
          read: false,
          type: msg.payload?.type || "info",
        };
        addNotification(notif);
        break;
      }
      case "heartbeat":
        break;
      case "auth":
        break;
      default:
        break;
    }
  }

  private startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: "heartbeat" }));
        } catch (e) {
          // 忽略
        }
      }
    }, 30000);
  }

  private stopHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      console.log("[WS] 尝试重连...");
      this.connect();
    }, 3000);
  }

  isConnected() {
    return this.connected;
  }
}

export const wsService = new WSService();
export default wsService;
