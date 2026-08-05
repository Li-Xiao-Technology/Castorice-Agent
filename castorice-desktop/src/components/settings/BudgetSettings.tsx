import { useEffect, useState, useCallback, useRef } from "react";
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
  Save,
  Shield,
  Activity,
  Settings2,
} from "lucide-react";
import api from "@/services/api";

type BudgetStatus = {
  enabled: boolean;
  throttled: boolean;
  paused: boolean;
  hourly: { tokens: number; calls: number; limit: number; used_pct: number; ttl_seconds: number };
  daily: { tokens: number; calls: number; limit: number; used_pct: number; ttl_seconds: number };
  config: {
    enabled: boolean;
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

const PRESETS = {
  relaxed: {
    label: "宽松",
    values: {
      hourly_token_limit: 500_000,
      daily_token_limit: 5_000_000,
      hourly_call_limit: 1000,
      per_session_thinking_steps: 32,
      autonomous_quick_min_interval: 30,
      autonomous_deep_min_interval: 300,
      throttle_threshold: 0.85,
      pause_threshold: 0.98,
    },
  },
  standard: {
    label: "标准",
    values: {
      hourly_token_limit: 200_000,
      daily_token_limit: 2_000_000,
      hourly_call_limit: 500,
      per_session_thinking_steps: 16,
      autonomous_quick_min_interval: 60,
      autonomous_deep_min_interval: 600,
      throttle_threshold: 0.7,
      pause_threshold: 0.95,
    },
  },
  strict: {
    label: "严格",
    values: {
      hourly_token_limit: 50_000,
      daily_token_limit: 500_000,
      hourly_call_limit: 200,
      per_session_thinking_steps: 8,
      autonomous_quick_min_interval: 300,
      autonomous_deep_min_interval: 1800,
      throttle_threshold: 0.5,
      pause_threshold: 0.8,
    },
  },
};

type PresetKey = keyof typeof PRESETS;

function formatNumber(n: number): string {
  if (!n) return "∞";
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

export default function BudgetSettings() {
  const [status, setStatus] = useState<BudgetStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState<Record<string, number | boolean>>({
    enabled: true,
  });
  const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set());
  const dirtyFieldsRef = useRef<Set<string>>(new Set());

  const syncDirtyRef = (next: Set<string>) => {
    dirtyFieldsRef.current = next;
    setDirtyFields(next);
  };

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.costBudget();
      if (data.success) {
        setStatus(data);
        const currentDirty = dirtyFieldsRef.current;
        // 始终做字段级合并：保留本地已有的值（尤其是 enabled），
        // 只同步后端返回的、且用户没在编辑的字段
        setConfig((prev) => {
          const merged = { ...prev };
          Object.keys(data.config).forEach((key) => {
            if (!currentDirty.has(key)) {
              merged[key] = data.config[key];
            }
          });
          return merged;
        });
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

  const markDirty = (key: string) => {
    syncDirtyRef(new Set(dirtyFieldsRef.current).add(key));
  };

  const handleToggleEnabled = () => {
    const newVal = !config.enabled;
    setConfig((prev) => ({ ...prev, enabled: newVal }));
    markDirty("enabled");
  };

  const handleNumChange = (key: string, value: string) => {
    const num = Number(value);
    if (isNaN(num)) return;
    setConfig((prev) => ({ ...prev, [key]: num }));
    markDirty(key);
  };

  const handleSliderChange = (key: string, value: number) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
    markDirty(key);
  };

  const applyPreset = (key: PresetKey) => {
    const preset = PRESETS[key];
    setConfig((prev) => ({ ...prev, ...preset.values }));
    Object.keys(preset.values).forEach((k) => markDirty(k));
  };

  const handleSave = async () => {
    if (dirtyFields.size === 0) return;
    setSaving(true);
    try {
      const payload: Record<string, number | boolean> = {};
      dirtyFields.forEach((key) => {
        payload[key] = config[key];
      });
      await api.costBudgetUpdate(payload as any);
      syncDirtyRef(new Set());
      await fetchStatus();
    } catch (e) {
      // 静默
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("确定要重置成本闸统计吗？")) return;
    try {
      await api.costBudgetReset();
      await fetchStatus();
    } catch (e) {
      // 静默
    }
  };

  const enabled = config.enabled !== false;

  return (
    <div className="space-y-6">
      {/* 顶部：总开关 + 状态 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
            enabled ? "bg-gradient-to-br from-rose-400 to-pink-600" : "bg-abyss-700/50"
          }`}>
            <Wallet className={`w-5 h-5 ${enabled ? "text-abyss-950" : "text-biolum-300/40"}`} strokeWidth={2.5} />
          </div>
          <div>
            <h2 className="font-display text-lg text-biolum-100">成本闸控制</h2>
            <p className="text-xs text-biolum-300/40">
              {enabled ? "已启用：监控 token 消耗，超预算自动降频/暂停" : "已禁用：所有预算限制不生效"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* 总开关 */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-abyss-800/50 border border-biolum-500/10">
            <span className="text-xs text-biolum-300/60">总开关</span>
            <button
              onClick={handleToggleEnabled}
              className={`relative w-11 h-6 rounded-full transition-colors ${
                enabled ? "bg-emerald-500" : "bg-abyss-600"
              }`}
            >
              <motion.div
                animate={{ x: enabled ? 20 : 2 }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
                className="absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-lg"
              />
            </button>
          </div>

          {enabled && status && !status.paused && !status.throttled && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30">
              <Shield className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-medium text-emerald-300">运行正常</span>
            </div>
          )}
          {enabled && status?.throttled && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-500/15 border border-amber-500/30">
              <AlertTriangle className="w-4 h-4 text-amber-400 animate-pulse" />
              <span className="text-sm font-medium text-amber-300">降频模式</span>
            </div>
          )}
          {enabled && status?.paused && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-rose-500/15 border border-rose-500/30">
              <PauseCircle className="w-4 h-4 text-rose-400 animate-pulse" />
              <span className="text-sm font-medium text-rose-300">自主活动已暂停</span>
            </div>
          )}

          <button
            onClick={fetchStatus}
            disabled={loading}
            className="flex items-center justify-center w-9 h-9 rounded-lg bg-biolum-500/10 text-biolum-200 hover:bg-biolum-500/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
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

      {/* 禁用遮罩 */}
      <div className={`relative transition-opacity ${enabled ? "" : "opacity-50 pointer-events-none"}`}>
        {/* 实时消耗 */}
        <div>
          <h3 className="text-sm text-biolum-100 mb-3 flex items-center gap-2">
            <Activity className="w-4 h-4 text-biolum-400" />
            实时消耗
          </h3>
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
                  / {formatNumber(status?.config.hourly_call_limit || 0)}
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
          <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
            <h3 className="text-sm text-biolum-100 flex items-center gap-2">
              <Settings2 className="w-4 h-4 text-biolum-400" />
              预算配置
            </h3>

            <div className="flex items-center gap-2">
              <span className="text-xs text-biolum-300/40">预设：</span>
              {(Object.keys(PRESETS) as PresetKey[]).map((key) => (
                <button
                  key={key}
                  onClick={() => applyPreset(key)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium bg-abyss-700/50 border border-biolum-500/10 text-biolum-200 hover:border-biolum-500/30 hover:bg-abyss-700 transition-all"
                >
                  {PRESETS[key].label}
                </button>
              ))}
            </div>

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

          <div className="space-y-6">
            <Section title="Token 预算" icon={Wallet}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <NumField
                  label="每小时 Token 上限"
                  unit="K"
                  onChange={(v) => handleNumChange("hourly_token_limit", String(v * 1000))}
                  displayValue={(Number(config.hourly_token_limit) || 0) / 1000}
                  placeholder="0 = 不限"
                  step={50}
                  min={0}
                />
                <NumField
                  label="每天 Token 上限"
                  unit="M"
                  onChange={(v) => handleNumChange("daily_token_limit", String(v * 1_000_000))}
                  displayValue={(Number(config.daily_token_limit) || 0) / 1_000_000}
                  placeholder="0 = 不限"
                  step={0.5}
                  min={0}
                />
                <NumField
                  label="每小时调用次数"
                  unit="次"
                  onChange={(v) => handleNumChange("hourly_call_limit", String(v))}
                  displayValue={Number(config.hourly_call_limit) || 0}
                  placeholder="0 = 不限"
                  step={50}
                  min={0}
                />
              </div>
            </Section>

            <Section title="思考与自主循环" icon={Zap}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <NumField
                  label="会话最大思考步数"
                  unit="步"
                  onChange={(v) => handleNumChange("per_session_thinking_steps", String(v))}
                  displayValue={Number(config.per_session_thinking_steps) || 0}
                  placeholder="0 = 不限"
                  step={1}
                  min={0}
                />
                <NumField
                  label="快速循环最小间隔"
                  unit="秒"
                  onChange={(v) => handleNumChange("autonomous_quick_min_interval", String(v))}
                  displayValue={Number(config.autonomous_quick_min_interval) || 0}
                  step={10}
                  min={0}
                />
                <NumField
                  label="深度循环最小间隔"
                  unit="秒"
                  onChange={(v) => handleNumChange("autonomous_deep_min_interval", String(v))}
                  displayValue={Number(config.autonomous_deep_min_interval) || 0}
                  step={30}
                  min={0}
                />
              </div>
            </Section>

            <Section title="阈值设置" icon={Gauge}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <SliderField
                  label="降频阈值"
                  desc="达到此使用率后，自主活动频率加倍降低"
                  value={Number(config.throttle_threshold) || 0}
                  onChange={(v) => handleSliderChange("throttle_threshold", v)}
                />
                <SliderField
                  label="暂停阈值"
                  desc="达到此使用率后，暂停所有自主活动"
                  value={Number(config.pause_threshold) || 0}
                  onChange={(v) => handleSliderChange("pause_threshold", v)}
                />
              </div>
            </Section>
          </div>

          <div className="mt-5 pt-4 border-t border-biolum-500/10">
            <p className="text-[11px] text-biolum-300/40 leading-relaxed">
              <strong className="text-biolum-300/60">说明：</strong>
              用户主动发起的对话不受成本闸限制。所有值设为 0 表示不限制。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- 子组件 ----

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

function Section({ title, icon: Icon, children }: { title: string; icon: any; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-biolum-400" />
        <h4 className="text-sm font-medium text-biolum-200">{title}</h4>
      </div>
      {children}
    </div>
  );
}

function NumField({
  label,
  unit,
  onChange,
  displayValue,
  placeholder,
  step,
  min,
}: {
  label: string;
  unit: string;
  onChange: (v: number) => void;
  displayValue: number;
  placeholder?: string;
  step?: number;
  min?: number;
}) {
  return (
    <div>
      <label className="text-xs text-biolum-300/60 mb-1.5 block">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={displayValue}
          step={step || 1}
          min={min}
          placeholder={placeholder}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full px-3 py-2 pr-12 rounded-lg bg-abyss-800/50 border border-biolum-500/10 focus:border-biolum-500/30 focus:outline-none text-sm text-biolum-100 placeholder:text-biolum-300/30"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-biolum-300/40">
          {unit}
        </span>
      </div>
    </div>
  );
}

function SliderField({
  label,
  desc,
  value,
  onChange,
}: {
  label: string;
  desc: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-biolum-200">{label}</label>
        <span className="text-sm font-semibold text-biolum-100">{pct}%</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={pct}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className="w-full accent-biolum-400"
      />
      <p className="text-[11px] text-biolum-300/40 mt-1">{desc}</p>
    </div>
  );
}
