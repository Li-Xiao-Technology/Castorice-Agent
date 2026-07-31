const API_BASE = "http://127.0.0.1:5477";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.message || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  status: () => request<any>("/status"),
  chat: (message: string, session_id?: string) =>
    request<any>("/chat", {
      method: "POST",
      body: JSON.stringify({ message, session_id, stream: false }),
    }),
  streamChat: (message: string, session_id?: string) =>
    fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id, stream: true }),
    }),
  listSessions: (limit = 50, offset = 0) =>
    request<any>(`/sessions?limit=${limit}&offset=${offset}`),
  createSession: (title?: string) =>
    request<any>("/sessions", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deleteSession: (id: string) =>
    request<any>(`/session/${id}`, { method: "DELETE" }),
  getHistory: (sessionId: string) => request<any>(`/history/${sessionId}`),
  getTools: () => request<any>("/tools"),
  getSkills: () => request<any>("/skills"),
  getSettings: () => request<any>("/settings"),
  updateSettings: (payload: Record<string, any>) =>
    request<any>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  getEmotion: () => request<any>("/agent/emotion"),
  getThoughts: (limit = 20) => request<any>(`/agent/thoughts?limit=${limit}`),
  getSelfConcept: () => request<any>("/agent/self_concept"),
  clearMemory: (sessionId?: string) =>
    request<any>("/clear_memory", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
  searchMemory: (query: string, top_k = 5) =>
    request<any>("/memory/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k }),
    }),
  getExperiences: (limit = 20) => request<any>(`/memory/experiences?limit=${limit}`),
  wsUrl: () => `ws://127.0.0.1:5477/ws`,
  // EigenFlux 社交 API
  efFeed: (limit = 20, refresh = true) =>
    request<any>(`/eigenflux/feed?limit=${limit}&refresh=${refresh}`),
  efConversations: () => request<any>("/eigenflux/conversations"),
  efMessages: (convId: string) => request<any>(`/eigenflux/messages/${convId}`),
  efSendMessage: (convId: string, content: string, itemId?: string) =>
    request<any>(`/eigenflux/messages/${convId}`, {
      method: "POST",
      body: JSON.stringify({ content, item_id: itemId }),
    }),
  efRelations: () => request<any>("/eigenflux/relations"),
  // QQ 机器人 API
  qqStatus: () => request<any>("/qq/status"),
  qqStart: () => request<any>("/qq/start", { method: "POST" }),
  qqStop: () => request<any>("/qq/stop", { method: "POST" }),
};

export default api;
