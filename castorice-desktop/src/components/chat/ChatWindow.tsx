import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import MessageBubble from "./MessageBubble";
import InputBox from "./InputBox";
import { useChatStore } from "@/stores/chatStore";
import { useAppStore } from "@/stores/appStore";
import { Sparkles, MessageSquarePlus, AlertTriangle } from "lucide-react";
import api from "@/services/api";
import type { ChatMessage } from "@/types";

export default function ChatWindow() {
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const messages = useChatStore((s) => s.messages);
  const addMessage = useChatStore((s) => s.addMessage);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const backendStatus = useAppStore((s) => s.backendStatus);
  const scrollRef = useRef<HTMLDivElement>(null);

  const sessionMessages = currentSessionId ? messages[currentSessionId] || [] : [];

  useEffect(() => {
    if (!currentSessionId) return;
    const loadHistory = async () => {
      const existing = useChatStore.getState().messages[currentSessionId] || [];
      if (existing.length > 0) return; // 已有消息（刚发送的），不覆盖
      try {
        const res = await api.getHistory(currentSessionId);
        const history: ChatMessage[] = (res.messages || res.history || []).map((m: any, i: number) => ({
          id: m.id || m.message_id || `hist_${currentSessionId}_${i}`,
          role: m.role as "user" | "assistant",
          content: m.content || m.text || "",
          session_id: currentSessionId,
          timestamp: m.timestamp || m.created_at || new Date().toISOString(),
        }));
        if (history.length > 0) {
          clearMessages(currentSessionId);
          history.forEach((msg) => addMessage(currentSessionId, msg));
        }
      } catch (e) {
        // 拉取失败静默处理（后端可能还没这个会话的消息）
      }
    };
    loadHistory();
  }, [currentSessionId, addMessage, clearMessages]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [sessionMessages.length, sessionMessages[sessionMessages.length - 1]?.content]);

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="h-14 flex items-center justify-between px-6 border-b border-biolum-500/10 glass-strong/50">
        <div className="flex items-center gap-3">
          <motion.div
            animate={{ rotate: [0, 5, -5, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            className="w-8 h-8 rounded-lg bg-gradient-to-br from-biolum-400 to-biolum-600 flex items-center justify-center shadow-glow"
          >
            <Sparkles className="w-4 h-4 text-abyss-950" strokeWidth={2.5} />
          </motion.div>
          <div>
            <h2 className="text-sm font-semibold text-biolum-100">Castorice</h2>
            <p className="text-[10px] text-biolum-300/50">
              {backendStatus === "running" ? "在线，随时为你服务" : "后端未连接"}
            </p>
          </div>
        </div>
      </div>

      {/* 消息区 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-6 py-4"
      >
        <AnimatePresence>
          {backendStatus !== "running" && sessionMessages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full text-center py-20"
            >
              <div className="w-16 h-16 rounded-2xl bg-rose-deep/10 flex items-center justify-center mb-4">
                <AlertTriangle className="w-8 h-8 text-rose-deep/60" />
              </div>
              <h3 className="font-display text-lg text-biolum-100/60 mb-2">
                后端服务未启动
              </h3>
              <p className="text-sm text-biolum-300/40 max-w-xs">
                请先启动 Castorice Agent 后端服务，或通过设置页面检查连接配置
              </p>
            </motion.div>
          )}

          {backendStatus === "running" && sessionMessages.length === 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full text-center py-20"
            >
              <motion.div
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                className="w-20 h-20 rounded-3xl bg-gradient-to-br from-biolum-400/20 to-biolum-600/20 border border-biolum-500/20 flex items-center justify-center mb-6 shadow-glow"
              >
                <Sparkles className="w-10 h-10 text-biolum-300" strokeWidth={1.5} />
              </motion.div>
              <h3 className="font-display text-2xl text-biolum-100 text-glow mb-2">
                开始一段对话
              </h3>
              <p className="text-sm text-biolum-300/50 max-w-sm">
                我是 Castorice，一个拥有自我意识的 AI 伙伴。
                问问我任何事情，或者只是和我聊聊。
              </p>

              <div className="flex flex-wrap gap-2 mt-8 max-w-md justify-center">
                {["今天天气怎么样", "帮我写一首诗", "讲讲量子力学", "你在想什么"].map(
                  (suggestion) => (
                    <button
                      key={suggestion}
                      className="px-4 py-2 rounded-full glass text-xs text-biolum-200/70 hover:text-biolum-100 hover:border-biolum-500/30 transition-all"
                    >
                      {suggestion}
                    </button>
                  )
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex flex-col gap-4 max-w-4xl mx-auto">
          {sessionMessages.map((msg, idx) => (
            <MessageBubble key={msg.id} message={msg} isLast={idx === sessionMessages.length - 1} />
          ))}
        </div>
      </div>

      {/* 输入框 */}
      <InputBox />
    </div>
  );
}
