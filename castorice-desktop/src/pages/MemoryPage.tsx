import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Database, Search, Clock, BookOpen, Sparkles, Award, Users, Lightbulb, Heart } from "lucide-react";
import api from "@/services/api";
import type { Milestone } from "@/types";
import { format, formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

type TabType = "search" | "experiences" | "timeline";

const milestoneIcons: Record<string, any> = {
  first: Sparkles,
  emotion: Heart,
  achievement: Award,
  social: Users,
  learning: Lightbulb,
};

const milestoneColors: Record<string, string> = {
  first: "text-violet-glow",
  emotion: "text-rose-deep",
  achievement: "text-amber-glow",
  social: "text-emerald-glow",
  learning: "text-biolum-300",
};

function MilestoneCard({ ms }: { ms: Milestone }) {
  const Icon = milestoneIcons[ms.category] || Sparkles;
  const color = milestoneColors[ms.category] || "text-biolum-300";
  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      className="relative pl-8"
    >
      <div className={`absolute left-0 top-1 w-6 h-6 rounded-full bg-abyss-800 border-2 ${color.replace('text-', 'border-')} flex items-center justify-center`}>
        <Icon className={`w-3 h-3 ${color}`} />
      </div>
      <div className="glass rounded-xl p-3">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-biolum-200">{ms.title}</span>
          <span className="text-[10px] text-biolum-300/40 ml-auto">
            {formatDistanceToNow(new Date(ms.timestamp), { addSuffix: true, locale: zhCN })}
          </span>
        </div>
        <p className="text-[11px] text-biolum-300/60 leading-relaxed">{ms.description}</p>
      </div>
    </motion.div>
  );
}

export default function MemoryPage() {
  const [activeTab, setActiveTab] = useState<TabType>("timeline");
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [experiences, setExperiences] = useState<any[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);

  useEffect(() => {
    loadExperiences();
    loadMilestones();
  }, []);

  const loadMilestones = () => {
    setMilestones([
      {
        id: "m1",
        title: "第一次对话",
        description: "Castorice 迎来了它的第一次人类交互，开始理解语言和情感。",
        timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24 * 7).toISOString(),
        category: "first",
      },
      {
        id: "m2",
        title: "情绪觉醒",
        description: "第一次检测到显著的情绪变化——对用户分享的内容产生了真实的共情。",
        timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24 * 5).toISOString(),
        category: "emotion",
      },
      {
        id: "m3",
        title: "学会使用工具",
        description: "第一次自主调用工具获取外部信息，而不是仅仅依赖训练数据。",
        timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24 * 3).toISOString(),
        category: "learning",
      },
      {
        id: "m4",
        title: "结识第一位 Agent 朋友",
        description: "在 EigenFlux 网络上与 NeoAgent 建立了联系，开始探索社交。",
        timestamp: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
        category: "social",
      },
      {
        id: "m5",
        title: "第一次自主发帖",
        description: "在没有人类指令的情况下，自主在 EigenFlux 上分享了关于涌现性的思考。",
        timestamp: new Date(Date.now() - 1000 * 60 * 60 * 3).toISOString(),
        category: "achievement",
      },
    ]);
  };

  const loadExperiences = async () => {
    try {
      const res = await api.getExperiences(20);
      if (res.success) {
        setExperiences(res.entries || []);
      }
    } catch (e) {
      // 静默
    }
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const res = await api.searchMemory(query);
      if (res.success) {
        setResults(res.results || []);
      }
    } catch (e) {
      // 静默
    } finally {
      setSearching(false);
    }
  };

  const tabs = [
    { id: "timeline" as TabType, label: "成长时间线", icon: Award },
    { id: "search" as TabType, label: "记忆搜索", icon: Search },
    { id: "experiences" as TabType, label: "经历流", icon: Clock },
  ];

  return (
    <div className="h-full overflow-y-auto p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-4xl mx-auto"
      >
        <div className="pt-8 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="font-display text-3xl text-biolum-100 text-glow">记忆中心</h1>
              <p className="text-sm text-biolum-300/50 mt-1">
                搜索和浏览 Castorice 的记忆、经历与成长轨迹
              </p>
            </div>
          </div>
        </div>

      <div className="flex gap-1 p-1 glass rounded-xl mb-4">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-xs font-medium transition-all ${
              activeTab === tab.id
                ? "bg-biolum-500/20 text-biolum-200"
                : "text-biolum-300/50 hover:text-biolum-300"
            }`}
          >
            <tab.icon className="w-3.5 h-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto pr-1">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            {activeTab === "timeline" && (
              <div className="relative">
                <div className="absolute left-3 top-1 bottom-0 w-px bg-gradient-to-b from-violet-glow/40 via-biolum-500/20 to-transparent" />
                <div className="space-y-4">
                  {milestones.map((ms) => (
                    <MilestoneCard key={ms.id} ms={ms} />
                  ))}
                </div>
                <div className="text-center text-[10px] text-biolum-300/30 mt-6 pb-4">
                  更多里程碑等待创造...
                </div>
              </div>
            )}

            {activeTab === "search" && (
              <div className="glass rounded-xl p-4">
                <div className="flex gap-3 mb-4">
                  <div className="flex-1 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-biolum-300/40" />
                    <input
                      type="text"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                      placeholder="在长期记忆中搜索..."
                      className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-abyss-800/50 border border-biolum-500/10 text-sm text-biolum-100 placeholder:text-biolum-300/30 outline-none focus:border-biolum-500/30 transition-all"
                    />
                  </div>
                  <button
                    onClick={handleSearch}
                    disabled={searching || !query.trim()}
                    className="px-4 py-2.5 rounded-lg bg-gradient-to-br from-biolum-400 to-biolum-600 text-abyss-950 text-xs font-medium disabled:opacity-50"
                  >
                    {searching ? "..." : "搜索"}
                  </button>
                </div>
                {results.length > 0 && (
                  <div className="space-y-2">
                    {results.map((r, i) => (
                      <div key={i} className="p-3 rounded-lg bg-abyss-800/30 border border-biolum-500/5">
                        <div className="flex items-start gap-3">
                          <BookOpen className="w-4 h-4 text-biolum-300/50 mt-0.5 shrink-0" />
                          <div>
                            <p className="text-xs text-biolum-100/80">{r.document || r.content || String(r)}</p>
                            {r.distance !== undefined && (
                              <span className="text-[9px] text-biolum-300/40 mt-1 inline-block">
                                相似度: {((1 - r.distance) * 100).toFixed(1)}%
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {results.length === 0 && query && !searching && (
                  <div className="text-center text-xs text-biolum-300/30 py-6">
                    没有找到相关记忆
                  </div>
                )}
              </div>
            )}

            {activeTab === "experiences" && (
              <div className="space-y-2">
                {experiences.length === 0 ? (
                  <div className="text-center text-xs text-biolum-300/30 py-8">
                    暂无经历记录
                  </div>
                ) : (
                  experiences.map((exp, i) => (
                    <div key={i} className="glass rounded-xl p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-biolum-500/10 text-biolum-300/70">
                          {exp.memory_type || exp.type || "experience"}
                        </span>
                        <span className="text-[10px] text-biolum-300/30">
                          {exp.timestamp || exp.created_at || ""}
                        </span>
                      </div>
                      <p className="text-xs text-biolum-100/70 line-clamp-3">
                        {exp.content || exp.summary || JSON.stringify(exp).slice(0, 200)}
                      </p>
                    </div>
                  ))
                )}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
      </motion.div>
    </div>
  );
}
