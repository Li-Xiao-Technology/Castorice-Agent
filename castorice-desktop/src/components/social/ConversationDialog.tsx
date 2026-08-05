import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Send, ArrowLeft } from "lucide-react";
import api from "@/services/api";
import type { Conversation, PrivateMessage } from "@/types";
import { format } from "date-fns";
import { zhCN } from "date-fns/locale";

function normalizeMessages(raw: any, conv: Conversation): PrivateMessage[] {
  // 尝试从各种可能的返回格式中提取消息列表
  let items: any[] = [];
  if (raw?.data?.messages) items = raw.data.messages;
  else if (raw?.data?.items) items = raw.data.items;
  else if (raw?.messages) items = raw.messages;
  else if (raw?.items) items = raw.items;
  else if (Array.isArray(raw?.data)) items = raw.data;

  if (items.length === 0) {
    // 没有真实数据，返回会话的 mock 消息
    return [
      {
        id: `mock_${conv.id}_1`,
        from: conv.peer,
        from_id: conv.peer_id,
        to: "我",
        to_id: "self",
        content: conv.last_message || "你好！最近怎么样？",
        timestamp: conv.last_timestamp,
        is_read: true,
      },
    ];
  }

  return items.map((item: any, idx: number) => ({
    id: item.id || `msg_${conv.id}_${idx}`,
    from: item.sender || item.from || item.sender_name || conv.peer,
    from_id: item.sender_id || item.from_id || conv.peer_id,
    to: item.recipient || item.to || "我",
    to_id: item.to_id || "self",
    content: item.content || item.message || item.summary || String(item),
    timestamp: item.timestamp || item.created_at || new Date().toISOString(),
    is_read: item.is_read ?? true,
  }));
}

export default function ConversationDialog({
  conversation,
  onClose,
}: {
  conversation: Conversation;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<PrivateMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const loadMessages = async () => {
    setLoading(true);
    try {
      const res = await api.efMessages(conversation.id);
      setMessages(normalizeMessages(res, conversation));
    } catch (e) {
      // API 失败，使用 mock
      setMessages(normalizeMessages(null, conversation));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMessages();
  }, [conversation.id]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSend = async () => {
    const content = input.trim();
    if (!content || sending) return;

    const tempMsg: PrivateMessage = {
      id: `temp_${Date.now()}`,
      from: "我",
      from_id: "self",
      to: conversation.peer,
      to_id: conversation.peer_id,
      content,
      timestamp: new Date().toISOString(),
      is_read: true,
    };

    setMessages((prev) => [...prev, tempMsg]);
    setInput("");
    setSending(true);

    try {
      await api.efSendMessage(conversation.id, content);
    } catch (e) {
      // 发送失败时保留消息（不回滚，避免用户困惑）
    } finally {
      setSending(false);
    }
  };

  const isSelf = (msg: PrivateMessage) => msg.from_id === "self" || msg.from === "我";

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-abyss-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.95, y: 20, opacity: 0 }}
          animate={{ scale: 1, y: 0, opacity: 1 }}
          exit={{ scale: 0.95, y: 20, opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => e.stopPropagation()}
          className="glass-strong w-full max-w-2xl h-[70vh] max-h-[600px] rounded-2xl border border-biolum-500/10 flex flex-col overflow-hidden shadow-2xl"
        >
          {/* 标题栏 */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-biolum-500/10 shrink-0">
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-biolum-300/50 hover:text-biolum-200 hover:bg-biolum-500/10 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
              <div className="w-9 h-9 rounded-full bg-biolum-500/20 flex items-center justify-center text-xs font-bold text-biolum-300">
                {conversation.peer.slice(0, 2).toUpperCase()}
              </div>
              <div>
                <div className="text-sm font-medium text-biolum-100">{conversation.peer}</div>
                <div className="text-[10px] text-biolum-300/40">
                  {conversation.unread_count > 0 ? `${conversation.unread_count} 条未读` : "暂无新消息"}
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-biolum-300/50 hover:text-biolum-200 hover:bg-biolum-500/10 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* 消息列表 */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {loading ? (
              <div className="text-center text-xs text-biolum-300/40 py-8">加载消息中...</div>
            ) : messages.length === 0 ? (
              <div className="text-center text-xs text-biolum-300/40 py-8">暂无消息</div>
            ) : (
              messages.map((msg) => {
                const self = isSelf(msg);
                return (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`flex ${self ? "justify-end" : "justify-start"}`}
                  >
                    <div className={`max-w-[75%] ${self ? "items-end" : "items-start"}`}>
                      <div
                        className={`px-3.5 py-2.5 rounded-2xl ${
                          self
                            ? "bg-gradient-to-br from-biolum-400 to-biolum-600 text-abyss-950 rounded-br-md"
                            : "bg-abyss-800 text-biolum-100 rounded-bl-md border border-biolum-500/10"
                        }`}
                      >
                        <p className="text-xs leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                      </div>
                      <div className={`text-[9px] text-biolum-300/30 mt-1 ${self ? "text-right" : "text-left"}`}>
                        {format(new Date(msg.timestamp), "HH:mm", { locale: zhCN })}
                      </div>
                    </div>
                  </motion.div>
                );
              })
            )}
          </div>

          {/* 输入框 */}
          <div className="p-3 border-t border-biolum-500/10 shrink-0">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                placeholder="输入消息..."
                className="flex-1 px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/10 text-sm text-biolum-100 placeholder:text-biolum-300/30 outline-none focus:border-biolum-500/30 transition-all"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || sending}
                className="px-4 py-2 rounded-lg bg-gradient-to-br from-biolum-400 to-biolum-600 text-abyss-950 text-xs font-medium disabled:opacity-50 transition-all flex items-center gap-1.5"
              >
                <Send className="w-3.5 h-3.5" />
                发送
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
