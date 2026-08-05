import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Wallet,
  Clock,
  Zap,
  AlertTriangle,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  Gauge,
  Settings,
  Save,
  Shield,
  Activity,
  Timer,
} from "lucide-react";
import api from "@/services/api";

type BudgetStatus = {
  throttled: boolean;
  paused: boolean;
  hourly: {
    tokens: number;
    calls: number;
    limit: number;
    used_pct: number;
    ttl_seconds: number;
  };
  daily: {
    tokens: number;
    calls: number;
    limit: number;
    used_pct: number;
    ttl_seconds: number;
  };
  config: {
    hourly_token_limit: number;
    daily_token_limit: number;
    hourly_call_limit: number;
    per_session_thinking_steps: number;
    autonomous_quick_min_interval: number;
    autonomous_deep_min_interval: number;
    throttle_threshold: number;
    pause_threshold: number;
  };
};

const FIELD_LABELS: Record<string, { label: string; icon: any; unit?: string }> = {
  hourly_token_limit: { label: "每小时 Token 上限", icon: Clock, unit: "K" },
  daily_token_limit: { label: "每天 Token 上限", icon: Clock, unit: "M" },
  hourly_call_limit: { label: "每小时调用次数上限", icon: Activity, unit: "次" },
  per_session_thinking_steps: { label: "每会话 ThinkingLoop 步数", icon: Zap, unit: "步" },
  autonomous_quick_min_interval: { label: "快速自主循环最小间隔", icon: Timer, unit: "秒" },
  autonomous_deep_min_interval: { label: "深度自主循环最小间隔", icon: Timer, unit: "秒" },
  throttle_threshold: { label: "降频阈值", icon: Gauge, unit: "%" },
  pause_threshold: { label: "暂停阈值", icon: PauseCircle, unit: "%" },
};

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

function formatSeconds(s: number): string {
  if (s <= 0) return "已重置";
  if (s < 60) return `${s} 秒`;
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
  return `${Math.floor(s / 3600)} 时 ${Math.floor((s % 3600) / 60)} 分`;
}

function StatusBadge({ status }: { status: BudgetStatus }) {
  if (status.paused) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-rose-500/15 border border-rose-500/30">
        <PauseCircle className="w-4 h-4 text-rose-400 animate-pulse" />
        <span className="text-sm font-medium text-rose-300">自主活动已暂停</span>
      </div>
    );
  }
  if (status.throttled) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-500/15 border border-amber-500/30">
        <AlertTriangle className="w-4 h-4 text-amber-400 animate-pulse" />
        <span className="text-sm font-medium text-amber-300">降频模式</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30">
      <Shield className="w-4 h-4 text-emerald-400" />
      <span className="text-sm font-medium text-emerald-300">运行正常</span>
    </div>
  );
}

function UsageBar({
  label,
  icon: Icon,
  used,
  limit,
  pct,
  color,
  ttl,
}: {
  label: string;
  icon: any;
  used: number;
  limit: number;
  pct: number;
  color: string;
  ttl: number;
}) {
  const isDanger = pct >= 90;
  const isWarning = pct >= 70 && pct < 90;
  const barColor = isDanger
    ? "from-rose-500 to-rose-600"
    : isWarning
    ? "from-amber-500 to-amber-600"
    : color;

  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-lg bg-abyss-800 flex items-center justify-center ${
            isDanger ? "text-rose-400" : isWarning ? "text-amber-400" : "text-biolum-300"
          }`}>
            <Icon className="w-4 h-4" />
          </div>
          <span className="text-sm text-biolum-100">{label}</span>
        </div>
        <div className="text-right">
          <div className={`font-display text-lg font-semibold ${
            isDanger ? "text-rose-400" : isWarning ? "text-amber-400" : "text-biolum-100"
          }`}>
            {formatNumber(used)}
            <span className="text-xs text-biolum-300/40 font-normal"> / {formatNumber(limit)}</span>
          </div>
        </div>
      </div>
      <div className="h-2 bg-abyss-800 rounded-full overflow-hidden mb-2">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(pct, 100)}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={`h-full bg-gradient-to-r ${barColor} rounded-full`}
        />
      </div>
      <div className="flex items-center justify-between text-[10px] text-biolum-300/40">
        <span>已使用 {pct.toFixed(1)}%</span>
        <span>距离重置 {formatSeconds(ttl)}</span>
      </div>
    </div>
  );
}

export default function BudgetPage() {
  const [status, setStatus] = useState<BudgetStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<Record<string, number>>({});
  const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set());

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.costBudget();
      if (data.success) {
        setStatus(data);
        setConfig(data.config);
        setDirtyFields(new Set());
      }
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const handleChange = (key: string, value: string) => {
    const num = Number(value);
    if (isNaN(num)) return;

    // 百分比字段处理（0-1 之间）
    let finalValue = num;
    if (key === "throttle_threshold" || key === "pause_threshold") {
      if (num > 1) finalValue = num / 100; // 输入 70 → 0.7
    }

    setConfig((prev) => ({ ...prev, [key]: finalValue }));
    setDirtyFields((prev) => new Set(prev).add(key));
  };

  const handleSave = async () => {
    if (dirtyFields.size === 0) return;
    setSaving(true);
    try {
      const payload: Record<string, number> = {};
      dirtyFields.forEach((key) => {
        payload[key] = config[key];
      });
      await api.costBudgetUpdate(payload);
      setDirtyFields(new Set());
      await fetchStatus();
    } catch (e) {
      // 静默
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("确定要重置成本闸统计吗？这将清空当前的 token 消耗和调用次数。")) return;
    try {
      await api.costBudgetReset();
      await fetchStatus();
    } catch (e) {
      // 静默
    }
  };

  const renderConfigField = (key: string) => {
    const field = FIELD_LABELS[key];
    if (!field) return null;
    const Icon = field.icon;
    const value = config[key];
    const original = (status?.config as Record<string, number>)?.[key];
    const isDirty = dirtyFields.has(key);

    // 显示值：百分比字段转成 0-100
    let displayValue = value;
    if (key === "throttle_threshold" || key === "pause_threshold") {
      displayValue = Math.round(value * 100);
    }

    return (
      <div key={key} className="relative">
        <label className="flex items-center gap-2 text-xs text-biolum-300/60 mb-1.5">
          <Icon className="w-3.5 h-3.5" />
          {field.label}
          {isDirty && (
            <span className="ml-auto text-[10px] text-amber-400">已修改</span>
          )}
        </label>
        <div className="relative">
          <input
            type="number"
            value={displayValue}
            onChange={(e) => handleChange(key, e.target.value)}
            className={`w-full px-3 py-2 pr-10 rounded-lg bg-abyss-800/50 border text-sm text-biolum-100 placeholder:text-biolum-300/30 focus:outline-none transition-all ${
              isDirty
                ? "border-amber-500/50 focus:border-amber-500/80"
                : "border-biolum-500/10 focus:border-biolum-500/30"
            }`}
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-biolum-300/40">
            {field.unit}
          </span>
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-400 to-pink-600 flex items-center justify-center shadow-glow">
              <Wallet className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">
                成本闸控制
              </h1>
              <p className="text-sm text-biolum-300/50 mt-0.5">
                实时监控 token 消耗，灵活调整预算上限
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {status && <StatusBadge status={status} />}
            <button
              onClick={fetchStatus}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-biolum-500/10 text-biolum-200 hover:bg-biolum-500/20 transition-all disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              <span className="text-sm">刷新</span>
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 transition-all"
            >
              <RotateCcw className="w-4 h-4" />
              <span className="text-sm">重置统计</span>
            </button>
          </div>
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {!status && loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="text-biolum-300/50 text-sm">加载中...</div>
          </div>
        ) : (
          <div className="space-y-6">
            {/* 使用概览 */}
            <div>
              <h2 className="font-display text-sm text-biolum-100 mb-3 flex items-center gap-2">
                <Activity className="w-4 h-4 text-biolum-400" />
                实时消耗
              </h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <UsageBar
                  label="本小时 Token 消耗"
                  icon={Clock}
                  used={status?.hourly.tokens || 0}
                  limit={status?.hourly.limit || 1}
                  pct={status?.hourly.used_pct || 0}
                  color="from-biolum-400 to-biolum-600"
                  ttl={status?.hourly.ttl_seconds || 0}
                />
                <UsageBar
                  label="本日 Token 消耗"
                  icon={Clock}
                  used={status?.daily.tokens || 0}
                  limit={status?.daily.limit || 1}
                  pct={status?.daily.used_pct || 0}
                  color="from-emerald-400 to-emerald-600"
                  ttl={status?.daily.ttl_seconds || 0}
                />
              </div>

              {/* 调用次数 */}
              <div className="grid grid-cols-2 gap-4 mt-4">
                <div className="glass rounded-xl p-4">
                  <div className="flex items-center gap-2 text-xs text-biolum-300/60 mb-2">
                    <Zap className="w-3.5 h-3.5" />
                    本小时调用次数
                  </div>
                  <div className="font-display text-xl font-semibold text-biolum-100">
                    {status?.hourly.calls || 0}
                    <span className="text-xs text-biolum-300/40 font-normal">
                      {" "}
                      / {status?.config.hourly_call_limit || "∞"}
                    </span>
                  </div>
                </div>
                <div className="glass rounded-xl p-4">
                  <div className="flex items-center gap-2 text-xs text-biolum-300/60 mb-2">
                    <Activity className="w-3.5 h-3.5" />
                    本日调用次数
                  </div>
                  <div className="font-display text-xl font-semibold text-biolum-100">
                    {status?.daily.calls || 0}
                  </div>
                </div>
              </div>
            </div>

            {/* 配置面板 */}
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center justify-between mb-5">
                <h2 className="font-display text-sm text-biolum-100 flex items-center gap-2">
                  <Settings className="w-4 h-4 text-biolum-400" />
                  预算配置
                </h2>
                <button
                  onClick={handleSave}
                  disabled={dirtyFields.size === 0 || saving}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-biolum-500/20 text-biolum-100 hover:bg-biolum-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Save className={`w-4 h-4 ${saving ? "animate-spin" : ""}`} />
                  <span className="text-sm">
                    {dirtyFields.size > 0 ? `保存修改 (${dirtyFields.size})` : "已保存"}
                  </span>
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {Object.keys(config).map((key) => renderConfigField(key))}
              </div>

              <div className="mt-5 pt-4 border-t border-biolum-500/10">
                <p className="text-[11px] text-biolum-300/40 leading-relaxed">
                  <strong className="text-biolum-300/60">说明：</strong>
                  当预算使用率达到「降频阈值」时，自主活动频率将加倍降低；
                  达到「暂停阈值」时，所有自主活动将暂停。
                  用户主动发起的对话不受影响。
                  设为 0 表示不限制。
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
