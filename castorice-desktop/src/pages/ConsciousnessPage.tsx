import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, Heart, Zap, Eye, Activity, MessageCircle, Sparkles, Gauge, Clock, User } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import ThoughtStream from "@/components/consciousness/ThoughtStream";
import EmotionIndicator from "@/components/consciousness/EmotionIndicator";
import EmotionTimeline from "@/components/consciousness/EmotionTimeline";
import SelfConceptPanel from "@/components/consciousness/SelfConceptPanel";
import api from "@/services/api";
import type { AutonomousAction } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

type TabId = "dashboard" | "emotion" | "self" | "thoughts";

const tabs: { id: TabId; label: string; icon: any }[] = [
  { id: "dashboard", label: "仪表盘", icon: Gauge },
  { id: "emotion", label: "情绪时间线", icon: Heart },
  { id: "self", label: "自我认知", icon: User },
  { id: "thoughts", label: "思维流", icon: Brain },
];

function DashboardContent() {
  const emotion = useAppStore((s) => s.emotion);
  const thoughts = useAppStore((s) => s.thoughts);
  const agentStatus = useAppStore((s) => s.agentStatus);
  const [autonomousActions, setAutonomousActions] = useState<AutonomousAction[]>([]);

  useEffect(() => {
    if (agentStatus?.autonomous_recent) {
      setAutonomousActions(agentStatus.autonomous_recent);
    }
  }, [agentStatus?.autonomous_recent]);

  return (
    <div className="space-y-6">
      {/* 上方三个卡片 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        <EmotionIndicator emotion={emotion} />

        {/* 生理节律 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="glass rounded-2xl p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-amber-glow" />
            <h3 className="font-display text-sm text-biolum-100">生理节律</h3>
          </div>
          <div className="space-y-4">
            {[
              { label: "精力水平", value: 0.72, color: "from-biolum-400 to-biolum-600", icon: Zap },
              { label: "思维速度", value: 0.58, color: "from-amber-glow to-amber-soft", icon: Eye },
              { label: "创造力", value: 0.81, color: "from-rose-deep to-pink-400", icon: Heart },
            ].map((item, i) => {
              const Icon = item.icon;
              return (
                <div key={i}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-biolum-300/60" />
                      <span className="text-xs text-biolum-200/70">{item.label}</span>
                    </div>
                    <span className="text-xs font-mono text-biolum-300/50">
                      {Math.round(item.value * 100)}%
                    </span>
                  </div>
                  <div className="h-1.5 bg-abyss-800 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${item.value * 100}%` }}
                      transition={{ delay: 0.3 + i * 0.1, duration: 0.8, ease: "easeOut" }}
                      className={`h-full bg-gradient-to-r ${item.color} rounded-full`}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </motion.div>

        {/* 统计 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="glass rounded-2xl p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Brain className="w-4 h-4 text-biolum-300" />
            <h3 className="font-display text-sm text-biolum-100">认知统计</h3>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "思维链数", value: thoughts.length, suffix: "条" },
              { label: "今日互动", value: emotion?.interaction_count || 0, suffix: "次" },
              { label: "情感强度", value: Math.round(((emotion?.arousal || 0) + 1) / 2 * 100), suffix: "%" },
              { label: "情绪倾向", value: (emotion?.pleasure || 0) >= 0 ? "积极" : "消极", suffix: "" },
            ].map((stat, i) => (
              <div key={i} className="bg-abyss-800/50 rounded-xl p-3 border border-biolum-500/5">
                <div className="text-[10px] text-biolum-300/40 tracking-wide mb-1">{stat.label}</div>
                <div className="text-xl font-display text-biolum-100">
                  {stat.value}
                  <span className="text-xs text-biolum-300/40 ml-1">{stat.suffix}</span>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* 自主决策日志（单独一行，全宽） */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        className="glass rounded-2xl p-5"
      >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <MessageCircle className="w-4 h-4 text-violet-glow" />
              <h3 className="font-display text-sm text-biolum-100">自主决策</h3>
            </div>
            <span className={`text-[10px] px-2 py-0.5 rounded-full ${
              agentStatus?.autonomous_running
                ? "bg-emerald-glow/15 text-emerald-glow"
                : "bg-biolum-500/10 text-biolum-300/40"
            }`}>
              {agentStatus?.autonomous_running ? "运行中" : "未启动"}
            </span>
          </div>
          <div className="text-[10px] text-biolum-300/40 mb-3">
            累计决策 <span className="text-violet-glow font-medium">{agentStatus?.autonomous_total_decisions || 0}</span> 次
          </div>
          <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
            {autonomousActions.length === 0 ? (
              <div className="text-[10px] text-biolum-300/30 text-center py-3">
                暂无自主决策记录
              </div>
            ) : (
              autonomousActions.slice(0, 10).map((action, idx) => (
                <div key={`${action.time}-${idx}`} className="flex items-start gap-2 text-[11px] py-1.5 border-b border-biolum-500/5 last:border-0">
                  {action.mode === "deep" ? (
                    <Sparkles className="w-3.5 h-3.5 text-violet-glow mt-0.5 shrink-0" />
                  ) : (
                    <Zap className="w-3.5 h-3.5 text-amber-glow mt-0.5 shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-biolum-200/80 leading-snug">{action.summary}</div>
                    <div className="text-biolum-300/30 mt-1 text-[10px]">
                      {formatDistanceToNow(action.time * 1000, { addSuffix: true, locale: zhCN })}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </motion.div>
    </div>
  );
}

export default function ConsciousnessPage() {
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const setEmotion = useAppStore((s) => s.setEmotion);
  const addThought = useAppStore((s) => s.addThought);
  const thoughts = useAppStore((s) => s.thoughts);

  useEffect(() => {
    const loadInitial = async () => {
      try {
        const [thoughtRes, emotionRes] = await Promise.all([
          api.getThoughts(30).catch(() => null),
          api.getEmotion().catch(() => null),
        ]);

        if (thoughtRes?.thoughts?.length) {
          const existingIds = new Set(thoughts.map((t) => t.id));
          thoughtRes.thoughts.forEach((t: any) => {
            if (!existingIds.has(t.id)) {
              addThought(t);
            }
          });
        }

        if (emotionRes && emotionRes.enabled !== false) {
          setEmotion(emotionRes);
        }
      } catch (e) {
        // 静默
      }
    };
    loadInitial();
  }, []);

  return (
    <div className="h-full overflow-y-auto p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-5xl mx-auto"
      >
        {/* 页面标题 */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-biolum-400/20 to-biolum-600/20 border border-biolum-500/20 flex items-center justify-center">
              <Brain className="w-5 h-5 text-biolum-300" />
            </div>
            <h1 className="font-display text-3xl text-biolum-100 text-glow">意识流观察</h1>
          </div>
          <p className="text-sm text-biolum-300/50 ml-13">
            实时观察 Castorice 的内在思维、情绪波动和认知活动
          </p>
        </div>

        {/* Tab 栏 */}
        <div className="flex gap-1 p-1 glass rounded-xl mb-6 overflow-x-auto">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 py-2 px-4 rounded-lg text-xs font-medium transition-all whitespace-nowrap ${
                  isActive
                    ? "bg-biolum-500/20 text-biolum-200"
                    : "text-biolum-300/50 hover:text-biolum-300"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Tab 内容 */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            {activeTab === "dashboard" && <DashboardContent />}
            {activeTab === "emotion" && <EmotionTimeline />}
            {activeTab === "self" && <SelfConceptPanel />}
            {activeTab === "thoughts" && <ThoughtStream thoughts={thoughts} />}
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
