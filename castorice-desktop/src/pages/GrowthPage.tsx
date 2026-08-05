import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Sprout, RefreshCw, Clock, BookOpen, Star, Milestone,
  TrendingUp, Calendar, Sparkles,
} from "lucide-react";
import api from "@/services/api";

type TimelineEvent = {
  id: string;
  timestamp: string;
  type: string;
  title: string;
  summary: string;
  importance: number;
  epoch?: string;
  memory_count?: number;
  milestones?: Array<any>;
};

type GrowthStats = {
  epoch: string;
  start_date: string;
  total_memories: number;
  total_knowledge_cards: number;
  total_milestones: number;
  activity_level: number;
  learning_rate: number;
  top_keywords: Array<{ word: string; count: number }>;
  epochs: Array<any>;
  recent_period: { days: number; new_memories: number; new_cards: number; new_milestones: number };
  generated_at: string;
};

export default function GrowthPage() {
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [stats, setStats] = useState<GrowthStats | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [tRes, sRes] = await Promise.all([
        api.growthTimeline(100),
        api.growthStats(30),
      ]);
      if (tRes.success) setTimeline(tRes.timeline || []);
      if (sRes.success) setStats(sRes);
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const typeIcons: Record<string, any> = {
    epoch: Clock,
    milestone: Milestone,
    memory: Sparkles,
    card: BookOpen,
    achievement: Star,
    default: Clock,
  };
  const typeColors: Record<string, string> = {
    epoch: "from-fuchsia-500 to-purple-600",
    milestone: "from-amber-400 to-orange-500",
    memory: "from-emerald-400 to-teal-500",
    card: "from-sky-400 to-blue-500",
    achievement: "from-rose-400 to-pink-500",
    default: "from-biolum-400 to-biolum-600",
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center shadow-glow">
              <Sprout className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">成长轨迹</h1>
              <p className="text-sm text-biolum-300/50 mt-0.5">Agent 的「人生故事」——时代、里程碑、记忆</p>
            </div>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-abyss-800/50 border border-biolum-500/20 hover:border-biolum-500/40 transition-all text-sm text-biolum-200"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>

        {/* 统计卡片 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard icon={BookOpen} label="记忆总数" value={stats.total_memories} sub={`当前时代: ${stats.epoch}`} color="emerald" />
            <StatCard icon={Star} label="知识卡片" value={stats.total_knowledge_cards} sub={`近30天 +${stats.recent_period?.new_cards ?? 0}`} color="sky" />
            <StatCard icon={Milestone} label="里程碑" value={stats.total_milestones} sub={`近30天 +${stats.recent_period?.new_milestones ?? 0}`} color="amber" />
            <StatCard icon={TrendingUp} label="活跃度" value={`${Math.round((stats.activity_level ?? 0) * 100)}%`} sub={`学习率 ${Math.round((stats.learning_rate ?? 0) * 100)}%`} color="fuchsia" />
          </div>
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 时间轴（左 2/3） */}
          <div className="lg:col-span-2">
            <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
              <h3 className="font-semibold text-biolum-100 mb-5 flex items-center gap-2">
                <Calendar className="w-4 h-4 text-biolum-400" />
                时间线
              </h3>

              {timeline.length === 0 ? (
                <div className="py-20 text-center text-biolum-300/40 text-sm">还没有成长记录，与 Agent 对话开始吧</div>
              ) : (
                <div className="relative">
                  {/* 时间轴竖线 */}
                  <div className="absolute left-[15px] top-2 bottom-2 w-px bg-gradient-to-b from-emerald-500/50 via-biolum-500/30 to-transparent" />

                  <div className="space-y-4">
                    {timeline.map((event, idx) => {
                      const Icon = typeIcons[event.type] || typeIcons.default;
                      const colorGrad = typeColors[event.type] || typeColors.default;
                      const date = new Date(event.timestamp);
                      const dateStr = `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;

                      return (
                        <motion.div
                          key={event.id}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: idx * 0.03 }}
                          className="relative pl-10"
                        >
                          {/* 节点圆点 */}
                          <div className={`absolute left-0 top-1 w-[30px] h-[30px] rounded-full bg-gradient-to-br ${colorGrad} flex items-center justify-center shadow-glow`}>
                            <Icon className="w-4 h-4 text-abyss-950" strokeWidth={2.5} />
                          </div>

                          <div className="rounded-xl bg-abyss-900/50 border border-biolum-500/10 p-3 hover:border-biolum-500/20 transition-all">
                            <div className="flex items-start justify-between gap-3 mb-1">
                              <h4 className="font-medium text-biolum-100 text-sm">{event.title}</h4>
                              <span className="text-[10px] text-biolum-300/40 whitespace-nowrap">{dateStr}</span>
                            </div>
                            {event.summary && <p className="text-xs text-biolum-300/60 leading-relaxed">{event.summary}</p>}
                            <div className="flex items-center gap-3 mt-2">
                              {event.epoch && <span className="text-[10px] px-2 py-0.5 rounded-full bg-fuchsia-500/10 text-fuchsia-300">{event.epoch}</span>}
                              {event.memory_count !== undefined && <span className="text-[10px] text-biolum-300/40">{event.memory_count} 条记忆</span>}
                              {event.importance !== undefined && (
                                <div className="flex gap-0.5">
                                  {Array.from({ length: 5 }).map((_, i) => (
                                    <Star
                                      key={i}
                                      className={`w-3 h-3 ${i < Math.ceil(event.importance * 5) ? "text-amber-400 fill-amber-400" : "text-biolum-300/20"}`}
                                    />
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </motion.div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 右侧：关键词 + 时代列表 */}
          <div className="space-y-6">
            {/* 热词云 */}
            <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
              <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-biolum-400" />
                高频关键词
              </h3>
              <div className="flex flex-wrap gap-2">
                {(stats?.top_keywords || []).map((kw, i) => {
                  const max = Math.max(...(stats?.top_keywords?.map((k) => k.count) || [1]));
                  const size = 11 + (kw.count / max) * 14;
                  const colors = ["text-fuchsia-300", "text-purple-300", "text-violet-300", "text-emerald-300", "text-sky-300", "text-amber-300"];
                  return (
                    <span
                      key={kw.word}
                      className={`${colors[i % colors.length]} font-medium`}
                      style={{ fontSize: `${size}px` }}
                    >
                      {kw.word}
                      <span className="text-biolum-300/30 ml-1 text-[10px]">{kw.count}</span>
                    </span>
                  );
                })}
                {(!stats?.top_keywords || stats.top_keywords.length === 0) && (
                  <span className="text-biolum-300/40 text-sm">暂无数据</span>
                )}
              </div>
            </div>

            {/* 时代列表 */}
            <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
              <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
                <Clock className="w-4 h-4 text-biolum-400" />
                成长时代
              </h3>
              <div className="space-y-2">
                {(stats?.epochs || []).map((ep: any, i: number) => (
                  <div key={i} className="rounded-lg bg-abyss-900/50 border border-biolum-500/5 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-biolum-100">{ep.name || `时代 ${i + 1}`}</span>
                      <span className="text-[10px] text-biolum-300/40">{ep.memory_count || 0} 记忆</span>
                    </div>
                    <p className="text-[11px] text-biolum-300/50 mt-1 line-clamp-2">{ep.summary || ep.description || ""}</p>
                  </div>
                ))}
                {(!stats?.epochs || stats.epochs.length === 0) && (
                  <span className="text-biolum-300/40 text-sm">暂无时代数据</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 统计卡片 ----
function StatCard({ icon: Icon, label, value, sub, color }: {
  icon: any; label: string; value: number | string; sub?: string;
  color: "emerald" | "sky" | "amber" | "fuchsia";
}) {
  const colorMap = {
    emerald: "from-emerald-400/20 to-teal-500/5 border-emerald-500/20",
    sky: "from-sky-400/20 to-blue-500/5 border-sky-500/20",
    amber: "from-amber-400/20 to-orange-500/5 border-amber-500/20",
    fuchsia: "from-fuchsia-400/20 to-purple-500/5 border-fuchsia-500/20",
  };
  const iconColor = {
    emerald: "text-emerald-400",
    sky: "text-sky-400",
    amber: "text-amber-400",
    fuchsia: "text-fuchsia-400",
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-xl bg-gradient-to-br ${colorMap[color]} border p-3`}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className={`w-4 h-4 ${iconColor[color]}`} />
        <span className="text-xs text-biolum-300/60">{label}</span>
      </div>
      <div className="text-2xl font-semibold text-biolum-100">{value}</div>
      {sub && <div className="text-[10px] text-biolum-300/40 mt-0.5">{sub}</div>}
    </motion.div>
  );
}
