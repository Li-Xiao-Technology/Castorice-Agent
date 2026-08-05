import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus, MessageSquare, Trash2 } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import api from "@/services/api";
import type { Session } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

export default function Sidebar() {
  const sessions = useChatStore((s) => s.sessions);
  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const setSessions = useChatStore((s) => s.setSessions);
  const setCurrentSession = useChatStore((s) => s.setCurrentSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  useEffect(() => {
    loadSessions();
  }, []);

  const loadSessions = async () => {
    try {
      const res = await api.listSessions();
      const rawList: any[] = res.sessions || [];
      const list: Session[] = rawList
        .filter((s) => s.session_id || s.id)
        .map((s) => ({
          id: s.session_id || s.id,
          title:
            s.title ||
            s.summary ||
            `会话 ${(s.session_id || s.id || "").slice(0, 6)}`,
          created_at: s.created_at,
          updated_at: s.updated_at,
          message_count: s.message_count,
        }));
      setSessions(list);
      // 优先选择 localStorage 里保存的会话（如果在列表中存在）
      const saved = useChatStore.getState().currentSessionId;
      if (saved && list.find((s) => s.id === saved)) {
        setCurrentSession(saved);
      } else if (list.length > 0) {
        setCurrentSession(list[0].id);
      } else {
        // 完全没有会话，自动创建一个默认会话
        try {
          const res = await api.createSession();
          if (res.success && res.session_id) {
            setCurrentSession(res.session_id);
            // 重新加载列表
            const res2 = await api.listSessions();
            const rawList2: any[] = res2.sessions || [];
            const list2: Session[] = rawList2
              .filter((s) => s.session_id || s.id)
              .map((s) => ({
                id: s.session_id || s.id,
                title:
                  s.title ||
                  s.summary ||
                  `会话 ${(s.session_id || s.id || "").slice(0, 6)}`,
                created_at: s.created_at,
                updated_at: s.updated_at,
                message_count: s.message_count,
              }));
            setSessions(list2);
          }
        } catch {
          // 创建失败静默处理
        }
      }
    } catch (e) {
      // 后端未启动时静默失败
    }
  };

  const handleNewSession = async () => {
    try {
      const res = await api.createSession();
      if (res.success) {
        setCurrentSession(res.session_id);
        loadSessions();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await api.deleteSession(id);
      deleteSession(id);
    } catch (e) {
      console.error(e);
    }
  };

  const validSessions = sessions
    .filter((s) => s && s.id)
    .filter((s, idx, arr) => arr.findIndex((x) => x.id === s.id) === idx) // 去重
    .sort((a, b) => {
      const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return tb - ta; // 最近更新的在前
    });

  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[10px] font-medium text-biolum-300/40 tracking-widest uppercase">
          会话
        </span>
        <button
          onClick={handleNewSession}
          className="p-1.5 rounded-lg text-biolum-300/50 hover:text-biolum-200 hover:bg-biolum-500/10 transition-all"
          title="新建会话"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      <div className="flex flex-col gap-1 overflow-y-auto max-h-[calc(100vh-420px)] pr-1">
        <AnimatePresence mode="popLayout">
          {validSessions.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center py-6 text-biolum-300/30 text-xs"
            >
              暂无会话
            </motion.div>
          ) : (
            validSessions.map((session) => (
              <motion.button
                key={session.id}
                layout
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -20 }}
                onClick={() => setCurrentSession(session.id)}
                onMouseEnter={() => setHoveredId(session.id)}
                onMouseLeave={() => setHoveredId(null)}
                className={`group relative flex items-center gap-2 px-3 py-2.5 rounded-xl text-left transition-all ${
                  currentSessionId === session.id
                    ? "bg-biolum-500/10 border border-biolum-500/20"
                    : "hover:bg-biolum-500/5 border border-transparent"
                }`}
              >
                <MessageSquare
                  className={`w-4 h-4 shrink-0 ${
                    currentSessionId === session.id
                      ? "text-biolum-300"
                      : "text-biolum-300/40"
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div
                    className={`text-sm truncate ${
                      currentSessionId === session.id
                        ? "text-biolum-100"
                        : "text-biolum-200/70"
                    }`}
                  >
                    {session.title ||
                      `会话 ${(session.id || "").slice(0, 6) || "新会话"}`}
                  </div>
                  <div className="text-[10px] text-biolum-300/30 mt-0.5">
                    {session.updated_at &&
                      formatDistanceToNow(new Date(session.updated_at), {
                        addSuffix: true,
                        locale: zhCN,
                      })}
                  </div>
                </div>

                <AnimatePresence>
                  {hoveredId === session.id &&
                    currentSessionId !== session.id && (
                      <motion.button
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.8 }}
                        onClick={(e) => handleDelete(e, session.id)}
                        className="p-1 rounded-md text-rose-deep/70 hover:text-rose-deep hover:bg-rose-deep/10 transition-all"
                        title="删除会话"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </motion.button>
                    )}
                </AnimatePresence>
              </motion.button>
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
