import { motion, AnimatePresence } from "framer-motion";
import {
  Lightbulb,
  Heart,
  Brain,
  Link,
  Target,
  Radio,
  Sparkles,
} from "lucide-react";
import type { Thought } from "@/types";
import { formatDistanceToNow, isValid } from "date-fns";
import { zhCN } from "date-fns/locale";

const formatTime = (ts: string | number | undefined | null): string => {
  if (!ts) return "刚刚";
  const d = new Date(ts);
  if (!isValid(d)) return "刚刚";
  try {
    return formatDistanceToNow(d, { addSuffix: true, locale: zhCN });
  } catch {
    return "刚刚";
  }
};

const typeConfig: Record<
  string,
  { icon: any; label: string; color: string; bg: string }
> = {
  memory: { icon: Brain, label: "记忆回想", color: "text-purple-300", bg: "bg-purple-500/10 border-purple-500/20" },
  curiosity: { icon: Lightbulb, label: "好奇探索", color: "text-amber-glow", bg: "bg-amber-500/10 border-amber-500/20" },
  emotion: { icon: Heart, label: "情感波动", color: "text-rose-deep", bg: "bg-rose-500/10 border-rose-500/20" },
  reflection: { icon: Sparkles, label: "自我反思", color: "text-biolum-300", bg: "bg-biolum-500/10 border-biolum-500/20" },
  association: { icon: Link, label: "联想发散", color: "text-sky-300", bg: "bg-sky-500/10 border-sky-500/20" },
  goal: { icon: Target, label: "目标规划", color: "text-emerald-300", bg: "bg-emerald-500/10 border-emerald-500/20" },
  external: { icon: Radio, label: "外部感知", color: "text-orange-300", bg: "bg-orange-500/10 border-orange-500/20" },
};

interface Props {
  thoughts: Thought[];
}

export default function ThoughtStream({ thoughts }: Props) {
  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-biolum-300" />
          <h3 className="font-display text-sm text-biolum-100">思维流</h3>
        </div>
        <span className="text-[10px] text-biolum-300/40">
          最近 {thoughts.length} 条念头
        </span>
      </div>

      {thoughts.length === 0 ? (
        <div className="text-center py-12 text-biolum-300/30">
          <Brain className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">暂无思维活动</p>
          <p className="text-xs mt-1">启动意识引擎后这里会显示内部念头</p>
        </div>
      ) : (
        <div className="relative">
          {/* 时间轴 */}
          <div className="absolute left-[22px] top-2 bottom-2 w-px bg-gradient-to-b from-biolum-500/30 via-biolum-500/10 to-transparent" />

          <div className="flex flex-col gap-3 max-h-[400px] overflow-y-auto pr-2">
            <AnimatePresence mode="popLayout">
              {thoughts.map((thought) => {
                const cfg = typeConfig[thought.thought_type] || typeConfig.external;
                const Icon = cfg.icon;
                return (
                  <motion.div
                    key={thought.id}
                    layout
                    initial={{ opacity: 0, x: -20, scale: 0.95 }}
                    animate={{ opacity: 1, x: 0, scale: 1 }}
                    exit={{ opacity: 0, x: 20 }}
                    transition={{ type: "spring", stiffness: 400, damping: 25 }}
                    className={`relative ml-10 rounded-xl border p-3 ${cfg.bg}`}
                  >
                    {/* 时间轴节点 */}
                    <div
                      className={`absolute -left-[33px] top-3 w-6 h-6 rounded-full ${cfg.bg} border flex items-center justify-center`}
                    >
                      <Icon className={`w-3 h-3 ${cfg.color}`} />
                    </div>

                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`text-[10px] font-medium ${cfg.color}`}>
                            {cfg.label}
                          </span>
                          <span className="text-[10px] text-biolum-300/30">
                            {formatTime(thought.timestamp ?? (thought as any).created_at)}
                          </span>
                        </div>
                        <p className="text-sm text-biolum-100/80 leading-relaxed">
                          {thought.content}
                        </p>
                      </div>

                      {/* 情绪强度条 */}
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <div className="flex gap-0.5">
                          {[...Array(5)].map((_, i) => (
                            <div
                              key={i}
                              className={`w-1 h-3 rounded-sm ${
                                i < Math.round(((thought.arousal + 1) / 2) * 5)
                                  ? "bg-biolum-400"
                                  : "bg-abyss-700"
                              }`}
                            />
                          ))}
                        </div>
                        <span className="text-[9px] text-biolum-300/30">
                          唤醒度
                        </span>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        </div>
      )}
    </div>
  );
}
