import { create } from "zustand";
import type { ChatMessage, Session } from "@/types";

const STORAGE_KEY = "castorice:chat:current_session";

interface ChatState {
  sessions: Session[];
  currentSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  isStreaming: boolean;
  currentStreamingId: string | null;

  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (id: string | null) => void;
  addMessage: (sessionId: string, msg: ChatMessage) => void;
  updateMessage: (sessionId: string, msgId: string, patch: Partial<ChatMessage>) => void;
  appendToMessage: (sessionId: string, msgId: string, chunk: string) => void;
  setStreaming: (streaming: boolean, msgId?: string | null) => void;
  clearMessages: (sessionId: string) => void;
  deleteSession: (sessionId: string) => void;
}

function loadSavedSession(): string | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved || null;
  } catch {
    return null;
  }
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessions: [],
  currentSessionId: loadSavedSession(),
  messages: {},
  isStreaming: false,
  currentStreamingId: null,

  setSessions: (sessions) => set({ sessions }),

  setCurrentSession: (id) => {
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {}
    set({ currentSessionId: id });
  },

  addMessage: (sessionId, msg) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: [...(state.messages[sessionId] || []), msg],
      },
    })),

  updateMessage: (sessionId, msgId, patch) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: (state.messages[sessionId] || []).map((m) =>
          m.id === msgId ? { ...m, ...patch } : m
        ),
      },
    })),

  appendToMessage: (sessionId, msgId, chunk) =>
    set((state) => ({
      messages: {
        ...state.messages,
        [sessionId]: (state.messages[sessionId] || []).map((m) =>
          m.id === msgId ? { ...m, content: m.content + chunk } : m
        ),
      },
    })),

  setStreaming: (streaming, msgId = null) =>
    set({ isStreaming: streaming, currentStreamingId: msgId }),

  clearMessages: (sessionId) =>
    set((state) => ({
      messages: { ...state.messages, [sessionId]: [] },
    })),

  deleteSession: (sessionId) =>
    set((state) => {
      const { [sessionId]: _, ...rest } = state.messages;
      const isCurrent = state.currentSessionId === sessionId;
      const nextSessionId = isCurrent
        ? state.sessions.find((s) => s.id !== sessionId)?.id || null
        : state.currentSessionId;
      try {
        if (isCurrent) {
          if (nextSessionId) localStorage.setItem(STORAGE_KEY, nextSessionId);
          else localStorage.removeItem(STORAGE_KEY);
        }
      } catch {}
      return {
        messages: rest,
        sessions: state.sessions.filter((s) => s.id !== sessionId),
        currentSessionId: nextSessionId,
      };
    }),
}));
