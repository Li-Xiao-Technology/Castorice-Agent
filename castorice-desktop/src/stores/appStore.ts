import { create } from "zustand";
import type { AgentStatus, Thought, EmotionState, EmotionHistoryPoint, SelfConcept, Notification } from "@/types";

export interface ProactiveMessage {
  id: string;
  content: string;
  timestamp: string;
  read?: boolean;
}

interface AppState {
  backendStatus: "idle" | "starting" | "running" | "stopped" | "error";
  agentStatus: AgentStatus | null;
  thoughts: Thought[];
  emotion: EmotionState | null;
  emotionHistory: EmotionHistoryPoint[];
  selfConcept: SelfConcept | null;
  proactiveMessages: ProactiveMessage[];
  notifications: Notification[];
  notificationsEnabled: boolean;
  activeView: "chat" | "consciousness" | "memory" | "tools" | "settings" | "social";
  sidebarCollapsed: boolean;

  setBackendStatus: (s: AppState["backendStatus"]) => void;
  setAgentStatus: (status: AgentStatus | null) => void;
  addThought: (thought: Thought) => void;
  setEmotion: (emotion: EmotionState | null) => void;
  addEmotionHistoryPoint: (point: EmotionHistoryPoint) => void;
  setSelfConcept: (sc: SelfConcept | null) => void;
  addProactiveMessage: (msg: ProactiveMessage) => void;
  clearProactiveMessages: () => void;
  addNotification: (n: Notification) => void;
  markNotificationRead: (id: string) => void;
  markAllNotificationsRead: () => void;
  clearNotifications: () => void;
  setNotificationsEnabled: (v: boolean) => void;
  setActiveView: (view: AppState["activeView"]) => void;
  toggleSidebar: () => void;
}

const MAX_EMOTION_HISTORY = 288; // 24小时 × 12次/小时（每5分钟）

export const useAppStore = create<AppState>((set) => ({
  backendStatus: "idle",
  agentStatus: null,
  thoughts: [],
  emotion: null,
  emotionHistory: [],
  selfConcept: null,
  proactiveMessages: [],
  notifications: [],
  notificationsEnabled: true,
  activeView: "chat",
  sidebarCollapsed: false,

  setBackendStatus: (s) => set({ backendStatus: s }),
  setAgentStatus: (status) => set({ agentStatus: status }),
  addThought: (thought) =>
    set((state) => {
      if (state.thoughts.some((t) => t.id === thought.id)) {
        return state;
      }
      return { thoughts: [thought, ...state.thoughts].slice(0, 50) };
    }),
  setEmotion: (emotion) => set({ emotion }),
  addEmotionHistoryPoint: (point) =>
    set((state) => ({
      emotionHistory: [...state.emotionHistory, point].slice(-MAX_EMOTION_HISTORY),
    })),
  setSelfConcept: (sc) => set({ selfConcept: sc }),
  addProactiveMessage: (msg) =>
    set((state) => ({
      proactiveMessages: [msg, ...state.proactiveMessages].slice(0, 20),
    })),
  clearProactiveMessages: () => set({ proactiveMessages: [] }),
  addNotification: (n) =>
    set((state) => ({
      notifications: [n, ...state.notifications].slice(0, 50),
    })),
  markNotificationRead: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n
      ),
    })),
  markAllNotificationsRead: () =>
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
    })),
  clearNotifications: () => set({ notifications: [] }),
  setNotificationsEnabled: (v) => set({ notificationsEnabled: v }),
  setActiveView: (view) => set({ activeView: view }),
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
