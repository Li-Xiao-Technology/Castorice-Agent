import { useRef, useEffect, useState, KeyboardEvent } from "react";
import { motion } from "framer-motion";
import { Send, Paperclip, Mic, StopCircle, Sparkles } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useAppStore } from "@/stores/appStore";
import api from "@/services/api";

export default function InputBox() {
  const [value, setValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const addMessage = useChatStore((s) => s.addMessage);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const appendToMessage = useChatStore((s) => s.appendToMessage);
  const setStreaming = useChatStore((s) => s.setStreaming);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const setCurrentSession = useChatStore((s) => s.setCurrentSession);
  const setSessions = useChatStore((s) => s.setSessions);
  const backendStatus = useAppStore((s) => s.backendStatus);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + "px";
    }
  }, [value]);

  const ensureSession = async (): Promise<string> => {
    if (currentSessionId) return currentSessionId;

    // 先从 store 里找已有会话
    const state = useChatStore.getState();
    if (state.sessions.length > 0) {
      const firstId = state.sessions[0].id;
      setCurrentSession(firstId);
      return firstId;
    }

    // store 里没有，就从后端拉取会话列表
    try {
      const listRes = await api.listSessions();
      const rawList: any[] = listRes.sessions || [];
      const mapped = rawList
        .filter((s) => s.session_id || s.id)
        .map((s) => ({
          id: s.session_id || s.id,
          title: s.title || s.summary || `会话 ${(s.session_id || s.id || "").slice(0, 6)}`,
          created_at: s.created_at,
          updated_at: s.updated_at,
          message_count: s.message_count,
        }));
      setSessions(mapped);

      // 优先选择 localStorage 里保存的
      const saved = localStorage.getItem("castorice:chat:current_session");
      if (saved && mapped.find((s) => s.id === saved)) {
        setCurrentSession(saved);
        return saved;
      }
      if (mapped.length > 0) {
        setCurrentSession(mapped[0].id);
        return mapped[0].id;
      }
    } catch {}

    // 实在没有任何会话，才创建新的
    const res = await api.createSession();
    if (res.success && res.session_id) {
      setCurrentSession(res.session_id);
      try {
        const listRes = await api.listSessions();
        const rawList: any[] = listRes.sessions || [];
        setSessions(
          rawList
            .filter((s) => s.session_id || s.id)
            .map((s) => ({
              id: s.session_id || s.id,
              title: s.title || s.summary || `会话 ${(s.session_id || s.id || "").slice(0, 6)}`,
              created_at: s.created_at,
              updated_at: s.updated_at,
              message_count: s.message_count,
            }))
        );
      } catch {}
      return res.session_id;
    }
    throw new Error("无法创建会话");
  };

  const handleSend = async () => {
    const text = value.trim();
    if (!text || isStreaming) return;
    if (backendStatus !== "running") return;

    let sessionId: string;
    try {
      sessionId = await ensureSession();
    } catch {
      return;
    }

    setIsSending(true);
    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();
    const now = new Date().toISOString();

    addMessage(sessionId, {
      id: userMsgId,
      role: "user",
      content: text,
      session_id: sessionId,
      timestamp: now,
    });

    addMessage(sessionId, {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      session_id: sessionId,
      timestamp: now,
      streaming: true,
    });

    setValue("");
    setStreaming(true, assistantMsgId);

    try {
      const response = await api.streamChat(text, sessionId);
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data:")) continue;
            try {
              const data = JSON.parse(trimmed.slice(5));
              if (data.chunk) {
                appendToMessage(sessionId, assistantMsgId, data.chunk);
              }
              if (data.final) {
                updateMessage(sessionId, assistantMsgId, {
                  content: data.answer || "",
                  streaming: false,
                });
              }
            } catch (e) {
              // 忽略解析错误
            }
          }
        }
      }

      // 如果没有流式内容，使用非流式接口
      const currentMsgs = useChatStore.getState().messages[sessionId] || [];
      const assistantMsg = currentMsgs.find((m) => m.id === assistantMsgId);
      if (assistantMsg && !assistantMsg.content && !assistantMsg.streaming) {
        const res = await api.chat(text, sessionId);
        updateMessage(sessionId, assistantMsgId, {
          content: res.answer || "",
          streaming: false,
        });
      } else if (assistantMsg && assistantMsg.streaming) {
        updateMessage(sessionId, assistantMsgId, { streaming: false });
      }
    } catch (e: any) {
      updateMessage(sessionId, assistantMsgId, {
        content: `⚠️ ${e.message || "发送失败，请检查后端服务是否启动"}`,
        streaming: false,
      });
    } finally {
      setStreaming(false);
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isDisabled = backendStatus !== "running" || isStreaming;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="p-4 border-t border-biolum-500/10"
    >
      <div
        className={`glass rounded-2xl p-2 input-glow transition-all duration-300 ${
          isDisabled ? "opacity-50" : ""
        }`}
      >
        <div className="flex items-end gap-2">
          <div className="flex gap-1 pb-2 pl-2">
            <button
              className="p-2 rounded-xl text-biolum-300/40 hover:text-biolum-200 hover:bg-biolum-500/10 transition-all"
              title="附件"
            >
              <Paperclip className="w-4 h-4" />
            </button>
          </div>

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              backendStatus !== "running"
                ? "后端服务未启动，请先启动 Castorice Agent..."
                : isStreaming
                ? "思考中..."
                : "和 Castorice 说点什么..."
            }
            disabled={isDisabled}
            rows={1}
            className="flex-1 bg-transparent text-sm text-biolum-100 placeholder:text-biolum-300/30 resize-none outline-none py-2 px-2 max-h-40 disabled:cursor-not-allowed"
          />

          <div className="flex gap-1 pb-2 pr-2">
            {isStreaming ? (
              <button
                className="p-2.5 rounded-xl bg-rose-deep/20 text-rose-deep hover:bg-rose-deep/30 transition-all"
                title="停止生成"
              >
                <StopCircle className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!value.trim() || isDisabled}
                className={`p-2.5 rounded-xl transition-all ${
                  value.trim() && !isDisabled
                    ? "bg-gradient-to-br from-biolum-400 to-biolum-600 text-abyss-950 shadow-glow hover:shadow-glow-lg hover:scale-105"
                    : "bg-biolum-500/10 text-biolum-300/30 cursor-not-allowed"
                }`}
              >
                <Send className="w-4 h-4" strokeWidth={2.2} />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between mt-2 px-2">
        <div className="flex items-center gap-1 text-[10px] text-biolum-300/30">
          <Sparkles className="w-3 h-3" />
          <span>Enter 发送 · Shift+Enter 换行</span>
        </div>
        <div className="text-[10px] text-biolum-300/20">
          {value.length} 字
        </div>
      </div>
    </motion.div>
  );
}
