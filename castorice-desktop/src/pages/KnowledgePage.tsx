import { useEffect, useState, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  BookOpen,
  Sparkles,
  Heart,
  Zap,
  Users,
  Lightbulb,
  Target,
  Shield,
  Filter,
  RefreshCw,
  Clock,
  Star,
  Tag,
} from "lucide-react";
import api from "@/services/api";

type KnowledgeCard = {
  card_id: string;
  title: string;
  content: string;
  card_type: string;
  keywords: string[];
  confidence: number;
  importance: number;
  valence: number;
  times_reinforced: number;
  created_at: string;
  last_updated_at: string;
};

const typeConfig: Record<string, { label: string; icon: any; color: string; bg: string }> = {
  fact: { label: "事实", icon: BookOpen, color: "text-sky-300", bg: "from-sky-500/20 to-sky-600/10" },
  preference: { label: "偏好", icon: Heart, color: "text-rose-300", bg: "from-rose-500/20 to-rose-600/10" },
  skill: { label: "技能", icon: Zap, color: "text-amber-300", bg: "from-amber-500/20 to-amber-600/10" },
  relationship: { label: "关系", icon: Users, color: "text-emerald-300", bg: "from-emerald-500/20 to-emerald-600/10" },
  pattern: { label: "模式", icon: Lightbulb, color: "text-purple-300", bg: "from-purple-500/20 to-purple-600/10" },
  lesson: { label: "教训", icon: Target, color: "text-orange-300", bg: "from-orange-500/20 to-orange-600/10" },
  value: { label: "价值观", icon: Shield, color: "text-indigo-300", bg: "from-indigo-500/20 to-indigo-600/10" },
  general: { label: "通用", icon: Sparkles, color: "text-biolum-300", bg: "from-biolum-500/20 to-biolum-600/10" },
};

export default function KnowledgePage() {
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState<string | null>(null);
  const [minImportance, setMinImportance] = useState(0);

  const fetchCards = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { limit: 100 };
      if (filterType) params.card_type = filterType;
      if (minImportance > 0) params.min_importance = minImportance;
      if (search.trim()) params.q = search.trim();
      const data = await api.learningCards(params);
      setCards(data.cards || []);
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  }, [filterType, minImportance, search]);

  useEffect(() => {
    const timer = setTimeout(fetchCards, 300);
    return () => clearTimeout(timer);
  }, [fetchCards]);

  // 按类型统计
  const typeStats = useMemo(() => {
    const stats: Record<string, number> = {};
    cards.forEach((c) => {
      stats[c.card_type] = (stats[c.card_type] || 0) + 1;
    });
    return stats;
  }, [cards]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center shadow-glow">
            <Sparkles className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">
              知识卡片
            </h1>
            <p className="text-sm text-biolum-300/50 mt-0.5">
              从交互经历中蒸馏的结构化知识，共 {cards.length} 张
            </p>
          </div>
        </div>

        {/* 搜索和筛选 */}
        <div className="flex flex-wrap gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-biolum-300/40" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索知识卡片..."
              className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-abyss-800/50 border border-biolum-500/10 text-biolum-100 text-sm placeholder:text-biolum-300/30 focus:outline-none focus:border-biolum-500/30 transition-all"
            />
          </div>

          <select
            value={filterType || ""}
            onChange={(e) => setFilterType(e.target.value || null)}
            className="px-4 py-2.5 rounded-xl bg-abyss-800/50 border border-biolum-500/10 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/30 transition-all"
          >
            <option value="">全部类型</option>
            {Object.entries(typeConfig).map(([key, cfg]) => (
              <option key={key} value={key}>
                {cfg.label} {typeStats[key] ? `(${typeStats[key]})` : ""}
              </option>
            ))}
          </select>

          <select
            value={minImportance}
            onChange={(e) => setMinImportance(Number(e.target.value))}
            className="px-4 py-2.5 rounded-xl bg-abyss-800/50 border border-biolum-500/10 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/30 transition-all"
          >
            <option value={0}>全部重要性</option>
            <option value={3}>重要性 ≥ 3</option>
            <option value={5}>重要性 ≥ 5</option>
            <option value={7}>重要性 ≥ 7</option>
          </select>

          <button
            onClick={fetchCards}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-biolum-500/10 text-biolum-200 hover:bg-biolum-500/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            <span className="text-sm">刷新</span>
          </button>
        </div>
      </div>

      {/* 卡片网格 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {loading && cards.length === 0 ? (
          <div className="flex items-center justify-center h-40">
            <div className="text-biolum-300/50 text-sm">加载中...</div>
          </div>
        ) : cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60">
            <Sparkles className="w-12 h-12 text-biolum-300/20 mb-3" />
            <p className="text-biolum-300/50">还没有知识卡片</p>
            <p className="text-biolum-300/30 text-sm mt-1">多和 Agent 交互，它会自动沉淀知识</p>
          </div>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
          >
            <AnimatePresence mode="popLayout">
              {cards.map((card, i) => {
                const cfg = typeConfig[card.card_type] || typeConfig.general;
                const Icon = cfg.icon;
                return (
                  <motion.div
                    key={card.card_id}
                    layout
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    transition={{ delay: i * 0.03 }}
                    className={`glass rounded-2xl p-5 bg-gradient-to-br ${cfg.bg} border border-biolum-500/5 relative overflow-hidden group hover:border-biolum-500/20 transition-all`}
                  >
                    {/* 类型标签 */}
                    <div className="flex items-center gap-2 mb-3">
                      <div className={`w-7 h-7 rounded-lg bg-abyss-900/50 flex items-center justify-center ${cfg.color}`}>
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <span className={`text-xs font-medium ${cfg.color}`}>{cfg.label}</span>
                      {card.times_reinforced > 1 && (
                        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-biolum-500/10 text-biolum-300/60 flex items-center gap-1">
                          <Star className="w-3 h-3" /> ×{card.times_reinforced}
                        </span>
                      )}
                    </div>

                    {/* 标题和内容 */}
                    <h4 className="font-display text-sm font-semibold text-biolum-100 mb-2 leading-snug">
                      {card.title}
                    </h4>
                    <p className="text-xs text-biolum-200/60 leading-relaxed line-clamp-3">
                      {card.content}
                    </p>

                    {/* 关键词 */}
                    {card.keywords?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-3">
                        {card.keywords.slice(0, 5).map((kw) => (
                          <span
                            key={kw}
                            className="text-[10px] px-1.5 py-0.5 rounded-md bg-abyss-900/40 text-biolum-300/50 flex items-center gap-1"
                          >
                            <Tag className="w-2.5 h-2.5" /> {kw}
                          </span>
                        ))}
                      </div>
                    )}

                    {/* 底部元信息 */}
                    <div className="flex items-center justify-between mt-4 pt-3 border-t border-biolum-500/5">
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1 text-biolum-300/40">
                          <Star className="w-3 h-3" />
                          <span className="text-[10px]">{card.importance.toFixed(0)}/10</span>
                        </div>
                        <div className="flex items-center gap-1 text-biolum-300/40">
                          <Shield className="w-3 h-3" />
                          <span className="text-[10px]">{Math.round(card.confidence * 100)}%</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 text-biolum-300/30">
                        <Clock className="w-3 h-3" />
                        <span className="text-[10px]">
                          {new Date(card.created_at).toLocaleDateString("zh-CN")}
                        </span>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  );
}
