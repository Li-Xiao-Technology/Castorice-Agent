import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  Heart,
  Server,
  Wifi,
  Database,
  Cpu,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Gauge,
  Clock,
  Moon,
  Sparkles,
  Brain,
  Zap,
  MessageSquare,
  Send,
  Plug,
  Wallet,
  BookOpen,
  Star,
  Eye,
  Target,
  Smile,
  User,
} from "lucide-react";
import api from "@/services/api";

type HealthStatus = {
  overall: "healthy" | "degraded" | "unhealthy" | "unknown" | "error";
  healthy_count: number;
  total_count: number;
  checks: {
    name: string;
    healthy: boolean;
    message: string;
    details: Record<string, any>;
    latency_ms: number;
    timestamp: number;
  }[];
  timestamp: number;
};

type LearningStatus = {
  running: boolean;
  is_sleeping: boolean;
  is_distilling: boolean;
  interaction_count: number;
  interactions_until_distill: number;
  idle_seconds: number;
  seconds_until_sleep: number;
  knowledge_cards: {
    total_cards: number;
    by_type: Record<string, number>;
  };
  sleep_history_count: number;
};

type TabId = "health" | "learning";

const tabs: { id: TabId; label: string; icon: any }[] = [
  { id: "health", label: "系统健康", icon: Activity },
  { id: "learning", label: "持续学习", icon: Brain },
];

function StatusBadge({ status, pending }: { status: boolean; pending?: boolean }) {
  if (pending) {
    return (
      <div className="flex items-center gap-1.5 text-biolum-300/60">
        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
        <span className="text-xs font-medium">检测中</span>
      </div>
    );
  }
  if (status) {
    return (
      <div className="flex items-center gap-1.5 text-emerald-400">
        <CheckCircle className="w-3.5 h-3.5" />
        <span className="text-xs font-medium">正常</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-rose-400">
      <XCircle className="w-3.5 h-3.5" />
      <span className="text-xs font-medium">异常</span>
    </div>
  );
}

function HealthPanel() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.health();
      setHealth(data);
    } catch (e: any) {
      setError(e.message || "获取健康状态失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  const overallIcon = {
    healthy: <CheckCircle className="w-6 h-6 text-emerald-400" />,
    degraded: <AlertTriangle className="w-6 h-6 text-amber-400" />,
    unhealthy: <XCircle className="w-6 h-6 text-rose-400" />,
    unknown: <Activity className="w-6 h-6 text-biolum-400" />,
    error: <XCircle className="w-6 h-6 text-rose-400" />,
  }[health?.overall || "unknown"];

  const overallLabel = {
    healthy: "全部正常",
    degraded: "部分降级",
    unhealthy: "系统异常",
    unknown: "检测中",
    error: "连接失败",
  }[health?.overall || "unknown"];

  const overallColor = {
    healthy: "text-emerald-400",
    degraded: "text-amber-400",
    unhealthy: "text-rose-400",
    unknown: "text-biolum-400",
    error: "text-rose-400",
  }[health?.overall || "unknown"];

  const checkIcons: Record<string, any> = {
    system: Cpu,
    llm: Zap,
    database: Database,
    memory: Database,
    emotion: Smile,
    self_concept: User,
    consciousness: Eye,
    motivation: Target,
    cost_budget: Wallet,
    continuous_learning: BookOpen,
    mcp: Plug,
    qq_bot: MessageSquare,
    telegram_bot: Send,
    eigenflux: Wifi,
  };

  const checkLabels: Record<string, string> = {
    system: "系统资源",
    llm: "LLM 服务",
    database: "数据库",
    memory: "记忆系统",
    emotion: "情感系统",
    self_concept: "自我概念",
    consciousness: "意识流",
    motivation: "动机系统",
    cost_budget: "成本闸",
    continuous_learning: "持续学习",
    mcp: "MCP 客户端",
    qq_bot: "QQ 机器人",
    telegram_bot: "Telegram 机器人",
    eigenflux: "EigenFlux 网络",
  };

  return (
    <div className="space-y-5">
      {/* 总览卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass rounded-2xl p-6"
      >
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            {overallIcon}
            <div>
              <h2 className={`font-display text-xl font-semibold ${overallColor}`}>
                {overallLabel}
              </h2>
              <p className="text-xs text-biolum-300/50 mt-0.5">
                {health ? `${health.healthy_count}/${health.total_count} 个子系统正常` : "正在检测..."}
              </p>
            </div>
          </div>
          <button
            onClick={fetchHealth}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-biolum-500/10 text-biolum-200 hover:bg-biolum-500/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            <span className="text-xs">刷新</span>
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm">
            {error}
          </div>
        )}

        {/* 子系统列表 */}
        <div className="space-y-3">
          {health?.checks?.map((check, i) => {
            const Icon = checkIcons[check.name] || Server;
            const isPending = (check as any).pending;
            const label = checkLabels[check.name] || check.name;
            return (
              <motion.div
                key={check.name}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center justify-between p-3 rounded-xl bg-abyss-800/50 border border-biolum-500/5"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                    isPending ? "bg-biolum-500/10" :
                    check.healthy ? "bg-emerald-500/10" : "bg-rose-500/10"
                  }`}>
                    <Icon className={`w-4 h-4 ${
                      isPending ? "text-biolum-300/60 animate-pulse" :
                      check.healthy ? "text-emerald-400" : "text-rose-400"
                    }`} />
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-biolum-100">
                      {label}
                    </h4>
                    <p className="text-xs text-biolum-300/50 mt-0.5">{check.message}</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs font-mono text-biolum-300/40">
                    {isPending ? "—" : `${check.latency_ms.toFixed(0)}ms`}
                  </span>
                  <StatusBadge status={check.healthy} pending={isPending} />
                </div>
              </motion.div>
            );
          })}
        </div>
      </motion.div>
    </div>
  );
}

function LearningPanel() {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.learningStatus();
      setStatus(data);
    } catch (e) {
      // 静默失败
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleDistill = async () => {
    setActionLoading("distill");
    try {
      await api.learningDistill(5);
      await fetchStatus();
    } catch (e) {
      // 静默
    } finally {
      setActionLoading(null);
    }
  };

  const handleSleep = async () => {
    setActionLoading("sleep");
    try {
      await api.learningSleep();
      await fetchStatus();
    } catch (e) {
      // 静默
    } finally {
      setActionLoading(null);
    }
  };

  const typeLabels: Record<string, string> = {
    fact: "事实",
    preference: "偏好",
    skill: "技能",
    relationship: "关系",
    pattern: "模式",
    lesson: "教训",
    value: "价值观",
    general: "通用",
  };

  return (
    <div className="space-y-5">
      {/* 状态概览 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass rounded-xl p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4 text-biolum-400" />
            <span className="text-xs text-biolum-300/60">知识卡片</span>
          </div>
          <div className="font-display text-2xl font-semibold text-biolum-100">
            {status?.knowledge_cards?.total_cards || 0}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="glass rounded-xl p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <MessageSquare className="w-4 h-4 text-amber-glow" />
            <span className="text-xs text-biolum-300/60">交互次数</span>
          </div>
          <div className="font-display text-2xl font-semibold text-biolum-100">
            {status?.interaction_count || 0}
          </div>
          <div className="text-[10px] text-biolum-300/40 mt-0.5">
            距离下次蒸馏: {status?.interactions_until_distill || 0} 次
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="glass rounded-xl p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-4 h-4 text-rose-300" />
            <span className="text-xs text-biolum-300/60">空闲时间</span>
          </div>
          <div className="font-display text-2xl font-semibold text-biolum-100">
            {status ? formatDuration(status.idle_seconds) : "0s"}
          </div>
          <div className="text-[10px] text-biolum-300/40 mt-0.5">
            距离睡眠: {status ? formatDuration(status.seconds_until_sleep) : "0s"}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="glass rounded-xl p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <Heart className="w-4 h-4 text-rose-400" />
            <span className="text-xs text-biolum-300/60">睡眠次数</span>
          </div>
          <div className="font-display text-2xl font-semibold text-biolum-100">
            {status?.sleep_history_count || 0}
          </div>
        </motion.div>
      </div>

      {/* 操作按钮 + 状态 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass rounded-2xl p-5"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-display text-sm text-biolum-100">学习控制</h3>
            <p className="text-xs text-biolum-300/50 mt-0.5">手动触发知识蒸馏或睡眠记忆巩固</p>
          </div>
          <div className="flex items-center gap-2">
            {status?.is_distilling && (
              <span className="text-xs px-2 py-1 rounded-full bg-amber-500/10 text-amber-300 flex items-center gap-1">
                <Sparkles className="w-3 h-3 animate-pulse" /> 蒸馏中...
              </span>
            )}
            {status?.is_sleeping && (
              <span className="text-xs px-2 py-1 rounded-full bg-indigo-500/10 text-indigo-300 flex items-center gap-1">
                <Moon className="w-3 h-3 animate-pulse" /> 睡眠中...
              </span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <button
            onClick={handleDistill}
            disabled={actionLoading === "distill" || status?.is_distilling}
            className="flex items-center justify-center gap-2 p-3 rounded-xl bg-biolum-500/10 text-biolum-100 hover:bg-biolum-500/20 transition-all disabled:opacity-50"
          >
            <Sparkles className={`w-4 h-4 ${actionLoading === "distill" ? "animate-spin" : ""}`} />
            <span className="text-sm">立即蒸馏</span>
          </button>
          <button
            onClick={handleSleep}
            disabled={actionLoading === "sleep" || status?.is_sleeping}
            className="flex items-center justify-center gap-2 p-3 rounded-xl bg-indigo-500/10 text-indigo-200 hover:bg-indigo-500/20 transition-all disabled:opacity-50"
          >
            <Moon className={`w-4 h-4 ${actionLoading === "sleep" ? "animate-spin" : ""}`} />
            <span className="text-sm">进入睡眠</span>
          </button>
        </div>
      </motion.div>

      {/* 知识卡片分类 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        className="glass rounded-2xl p-5"
      >
        <h3 className="font-display text-sm text-biolum-100 mb-4">知识卡片分布</h3>
        {status?.knowledge_cards?.by_type && Object.keys(status.knowledge_cards.by_type).length > 0 ? (
          <div className="space-y-3">
            {Object.entries(status.knowledge_cards.by_type).map(([type, count]: [string, any]) => {
              const total = status.knowledge_cards.total_cards || 1;
              const pct = (count / total) * 100;
              return (
                <div key={type}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-biolum-200/70">{typeLabels[type] || type}</span>
                    <span className="text-xs font-mono text-biolum-300/50">{count}</span>
                  </div>
                  <div className="h-1.5 bg-abyss-800 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.6, ease: "easeOut" }}
                      className="h-full bg-gradient-to-r from-biolum-400 to-biolum-600 rounded-full"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-biolum-300/40">还没有知识卡片，多和 Agent 聊聊吧～</p>
        )}
      </motion.div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export default function MonitorPage() {
  const [activeTab, setActiveTab] = useState<TabId>("health");

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center shadow-glow">
            <Gauge className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">
              系统监控
            </h1>
            <p className="text-sm text-biolum-300/50 mt-0.5">
              实时监测系统健康状态与持续学习进度
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl bg-abyss-800/50 w-fit">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
                  isActive
                    ? "bg-biolum-500/20 text-biolum-100"
                    : "text-biolum-300/50 hover:text-biolum-200"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span className="text-sm font-medium">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {activeTab === "health" && <HealthPanel />}
        {activeTab === "learning" && <LearningPanel />}
      </div>
    </div>
  );
}
