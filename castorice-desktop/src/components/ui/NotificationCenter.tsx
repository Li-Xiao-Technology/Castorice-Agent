import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, X, CheckCheck, Trash2, Brain, Heart, Radio, Info, AlertCircle } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import type { Notification } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

const typeIcons: Record<string, any> = {
  thought: Brain,
  emotion: Heart,
  eigenflux: Radio,
  system: AlertCircle,
  info: Info,
};

const typeColors: Record<string, string> = {
  thought: "text-violet-glow bg-violet-glow/10",
  emotion: "text-rose-deep bg-rose-deep/10",
  eigenflux: "text-emerald-glow bg-emerald-glow/10",
  system: "text-amber-glow bg-amber-glow/10",
  info: "text-biolum-300 bg-biolum-500/10",
};

function NotificationItem({ n }: { n: Notification }) {
  const Icon = typeIcons[n.type || "info"] || Info;
  const colorClass = typeColors[n.type || "info"] || typeColors.info;
  const markRead = useAppStore((s) => s.markNotificationRead);

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => markRead(n.id)}
      className={`p-3 rounded-xl border-b border-biolum-500/5 last:border-0 cursor-pointer transition-colors ${
        !n.read ? "bg-biolum-500/5" : "hover:bg-biolum-500/5"
      }`}
    >
      <div className="flex gap-3">
        <div className={`w-8 h-8 rounded-lg ${colorClass} flex items-center justify-center shrink-0`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-biolum-100">{n.title}</span>
            {!n.read && <span className="w-1.5 h-1.5 rounded-full bg-biolum-400 shrink-0" />}
          </div>
          <p className="text-[11px] text-biolum-300/60 line-clamp-2 leading-relaxed">{n.body}</p>
          <p className="text-[9px] text-biolum-300/30 mt-1">
            {formatDistanceToNow(new Date(n.timestamp), { addSuffix: true, locale: zhCN })}
          </p>
        </div>
      </div>
    </motion.div>
  );
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const notifications = useAppStore((s) => s.notifications);
  const markAllRead = useAppStore((s) => s.markAllNotificationsRead);
  const clearAll = useAppStore((s) => s.clearNotifications);

  const unreadCount = notifications.filter((n) => !n.read).length;

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative w-9 h-9 rounded-xl flex items-center justify-center text-biolum-300/60 hover:text-biolum-200 hover:bg-biolum-500/10 transition-all"
      >
        <Bell className="w-4.5 h-4.5" strokeWidth={1.8} />
        {unreadCount > 0 && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute top-1 right-1 min-w-[16px] h-4 px-1 rounded-full bg-rose-deep text-white text-[9px] font-bold flex items-center justify-center"
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </motion.span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-11 w-80 glass-strong rounded-2xl border border-biolum-500/10 shadow-2xl z-50 overflow-hidden"
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-biolum-500/10">
              <h3 className="text-sm font-medium text-biolum-100">通知中心</h3>
              <div className="flex items-center gap-1">
                {notifications.length > 0 && (
                  <>
                    <button
                      onClick={markAllRead}
                      className="p-1.5 rounded-lg text-biolum-300/50 hover:text-biolum-200 hover:bg-biolum-500/10 transition-colors"
                      title="全部已读"
                    >
                      <CheckCheck className="w-4 h-4" />
                    </button>
                    <button
                      onClick={clearAll}
                      className="p-1.5 rounded-lg text-biolum-300/50 hover:text-rose-deep hover:bg-rose-deep/10 transition-colors"
                      title="清空通知"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </>
                )}
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 rounded-lg text-biolum-300/50 hover:text-biolum-200 hover:bg-biolum-500/10 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="max-h-80 overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="py-12 text-center">
                  <Bell className="w-8 h-8 text-biolum-300/20 mx-auto mb-3" />
                  <p className="text-xs text-biolum-300/30">暂无通知</p>
                </div>
              ) : (
                notifications.map((n) => <NotificationItem key={n.id} n={n} />)
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
