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
  // P0/P3: 健康检查 + 持续学习 API
  health: () => request<any>("/health"),
  learningStatus: () => request<any>("/learning/status"),
  learningCards: (params?: { card_type?: string; min_importance?: number; limit?: number; q?: string }) => {
    const query = new URLSearchParams();
    if (params?.card_type) query.set("card_type", params.card_type);
    if (params?.min_importance) query.set("min_importance", String(params.min_importance));
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.q) query.set("q", params.q);
    const qs = query.toString();
    return request<any>(`/learning/cards${qs ? `?${qs}` : ""}`);
  },
  learningDistill: (max_cards = 5) =>
    request<any>(`/learning/distill?max_cards=${max_cards}`, { method: "POST" }),
  learningSleep: () => request<any>("/learning/sleep", { method: "POST" }),
  learningSleepHistory: (limit = 20) => request<any>(`/learning/sleep-history?limit=${limit}`),
  // 成本闸 API
  costBudget: () => request<any>("/cost-budget"),
  costBudgetUpdate: (payload: Record<string, any>) =>
    request<any>("/cost-budget", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  costBudgetReset: () =>
    request<any>("/cost-budget/reset", { method: "POST" }),
  // 人格画像 API
  personality: (force = false) => request<any>(`/personality?force=${force}`),
  personalityHistory: (days = 30) => request<any>(`/personality/history?days=${days}`),
  // 成长轨迹 API
  growthTimeline: (limit = 50) => request<any>(`/growth/timeline?limit=${limit}`),
  growthStats: (days = 30) => request<any>(`/growth/stats?days=${days}`),
  // 目标管理 API
  goals: (tree = true) => request<any>(`/goals?tree=${tree}`),
  goalsCreate: (payload: Record<string, any>) =>
    request<any>("/goals", { method: "POST", body: JSON.stringify(payload) }),
  goalsUpdate: (id: string, payload: Record<string, any>) =>
    request<any>(`/goals/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  goalsDelete: (id: string) => request<any>(`/goals/${id}`, { method: "DELETE" }),
  goalsSuggestions: () => request<any>("/goals/suggestions"),
  goalsAddMilestone: (id: string, payload: Record<string, any>) =>
    request<any>(`/goals/${id}/milestone`, { method: "POST", body: JSON.stringify(payload) }),
  goalsCompleteMilestone: (goalId: string, msId: string) =>
    request<any>(`/goals/${goalId}/milestone/${msId}`, { method: "PUT" }),
  // FTS5 消息搜索
  searchMessages: (query: string, session_id?: string, limit = 20) => {
    const qs = new URLSearchParams({ query, limit: String(limit) });
    if (session_id) qs.set("session_id", session_id);
    return request<any>(`/messages/search?${qs.toString()}`);
  },
  // LLM 供应商管理
  listProviders: () => request<any>("/llm/providers"),
  addProvider: (payload: Record<string, any>) =>
    request<any>("/llm/providers", { method: "POST", body: JSON.stringify(payload) }),
  updateProvider: (id: string, payload: Record<string, any>) =>
    request<any>(`/llm/providers/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteProvider: (id: string) =>
    request<any>(`/llm/providers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  // MCP 客户端 API
  mcpListServers: () => request<any>("/mcp/servers"),
  mcpAddServer: (payload: Record<string, any>) =>
    request<any>("/mcp/servers", { method: "POST", body: JSON.stringify(payload) }),
  mcpRemoveServer: (name: string) =>
    request<any>(`/mcp/servers/${encodeURIComponent(name)}`, { method: "DELETE" }),
  mcpStartAll: () => request<any>("/mcp/start", { method: "POST" }),
  mcpStopAll: () => request<any>("/mcp/stop", { method: "POST" }),
  mcpTools: () => request<any>("/mcp/tools"),
  // Telegram Bot API
  telegramStatus: () => request<any>("/telegram/status"),
  telegramStart: () => request<any>("/telegram/start", { method: "POST" }),
  telegramStop: () => request<any>("/telegram/stop", { method: "POST" }),
};

export default api;
