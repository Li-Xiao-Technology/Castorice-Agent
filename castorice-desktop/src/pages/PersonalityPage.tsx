import { useEffect, useState, useCallback } from "react";
import { motion } from "framer-motion";
import { User, RefreshCw, Smile, Zap, Crown, TrendingUp } from "lucide-react";
import api from "@/services/api";

type PersonalityData = {
  pad_baseline: { pleasure: number; arousal: number; dominance: number };
  pad_volatility: { pleasure: number; arousal: number; dominance: number };
  values_radar: Array<{ dimension_id: string; name: string; description: string; strength: number; trend: number }>;
  top_values: Array<{ dimension_id: string; name: string; strength: number }>;
  value_signature: string;
  traits: Array<{ word: string; weight: number; source: string }>;
  speaking_style: { formality: number; emotionality: number; verbosity: number };
  interaction_count: number;
  generated_at: string;
};

export default function PersonalityPage() {
  const [data, setData] = useState<PersonalityData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const res = await api.personality(force);
      if (res.success) setData(res);
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => fetchData(false), 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-fuchsia-400 to-purple-600 flex items-center justify-center shadow-glow">
              <User className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">人格画像</h1>
              <p className="text-sm text-biolum-300/50 mt-0.5">从情感、价值观、自我概念中涌现的 Agent 人格</p>
            </div>
          </div>
          <button
            onClick={() => fetchData(true)}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-abyss-800/50 border border-biolum-500/20 hover:border-biolum-500/40 transition-all text-sm text-biolum-200"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
        {data?.value_signature && (
          <div className="px-4 py-3 rounded-xl bg-gradient-to-r from-fuchsia-500/10 to-purple-500/10 border border-fuchsia-500/20">
            <span className="text-fuchsia-300 font-medium">价值观签名：</span>
            <span className="text-biolum-100 ml-2">{data.value_signature}</span>
            <span className="text-biolum-300/50 ml-4 text-sm">交互 {data.interaction_count} 次</span>
          </div>
        )}
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-6">
        {/* PAD 三维仪表 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <PADDial label="愉悦度" icon={Smile} value={data?.pad_baseline.pleasure ?? 0.5} volatility={data?.pad_volatility.pleasure ?? 0} color="emerald" />
          <PADDial label="唤醒度" icon={Zap} value={data?.pad_baseline.arousal ?? 0.3} volatility={data?.pad_volatility.arousal ?? 0} color="amber" />
          <PADDial label="支配度" icon={Crown} value={data?.pad_baseline.dominance ?? 0.5} volatility={data?.pad_volatility.dominance ?? 0} color="sky" />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 价值观雷达图 */}
          <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
            <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-biolum-400" />
              价值观维度
            </h3>
            <ValuesRadar data={data?.values_radar || []} />
          </div>

          {/* 性格标签云 */}
          <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
            <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
              <User className="w-4 h-4 text-biolum-400" />
              性格标签
            </h3>
            <TraitCloud traits={data?.traits || []} />
            <div className="mt-5 pt-4 border-t border-biolum-500/10">
              <h4 className="text-sm font-medium text-biolum-200 mb-3">说话风格</h4>
              <div className="space-y-3">
                <StyleBar label="正式度" value={data?.speaking_style.formality ?? 0.5} />
                <StyleBar label="情感性" value={data?.speaking_style.emotionality ?? 0.5} />
                <StyleBar label="冗长度" value={data?.speaking_style.verbosity ?? 0.5} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- PAD 仪表盘 ----
function PADDial({ label, icon: Icon, value, volatility, color }: {
  label: string; icon: any; value: number; volatility: number;
  color: "emerald" | "amber" | "sky";
}) {
  const colorMap = {
    emerald: "from-emerald-400 to-teal-500",
    amber: "from-amber-400 to-orange-500",
    sky: "from-sky-400 to-blue-500",
  };
  const pct = Math.round(value * 100);
  const circumference = 2 * Math.PI * 80;
  const offset = circumference - (value * 0.8 + 0.1) * circumference;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5"
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className={`w-4 h-4 text-${color}-400`} />
        <span className="text-sm font-medium text-biolum-200">{label}</span>
      </div>
      <div className="flex justify-center">
        <svg width="180" height="110" viewBox="0 0 200 120">
          <defs>
            <linearGradient id={`grad-${color}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={color === "emerald" ? "#34d399" : color === "amber" ? "#fbbf24" : "#38bdf8"} />
              <stop offset="100%" stopColor={color === "emerald" ? "#14b8a6" : color === "amber" ? "#f97316" : "#3b82f6"} />
            </linearGradient>
          </defs>
          {/* 背景弧 */}
          <path
            d="M 20 100 A 80 80 0 0 1 180 100"
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="12"
            strokeLinecap="round"
          />
          {/* 进度弧 */}
          <path
            d="M 20 100 A 80 80 0 0 1 180 100"
            fill="none"
            stroke={`url(#grad-${color})`}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease-out" }}
          />
          {/* 中心值 */}
          <text x="100" y="85" textAnchor="middle" className="fill-biolum-100" style={{ fontSize: "28px", fontWeight: 600 }}>
            {pct}
          </text>
          <text x="100" y="105" textAnchor="middle" className="fill-biolum-300/50" style={{ fontSize: "11px" }}>
            波动 {Math.round(volatility * 100)}%
          </text>
        </svg>
      </div>
    </motion.div>
  );
}

// ---- 价值观雷达图（纯 SVG）----
function ValuesRadar({ data }: { data: Array<{ name: string; strength: number }> }) {
  const size = 280;
  const center = size / 2;
  const radius = size / 2 - 40;
  const n = Math.max(data.length, 3);

  const pointAngle = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pointPos = (i: number, r: number) => [
    center + Math.cos(pointAngle(i)) * r,
    center + Math.sin(pointAngle(i)) * r,
  ];

  if (data.length === 0) {
    return <div className="h-[280px] flex items-center justify-center text-biolum-300/40 text-sm">暂无数据</div>;
  }

  // 数据多边形
  const dataPoints = data.map((d, i) => {
    const [x, y] = pointPos(i, radius * d.strength);
    return `${x},${y}`;
  }).join(" ");

  return (
    <div className="flex justify-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* 背景网格（5 层） */}
        {[0.2, 0.4, 0.6, 0.8, 1.0].map((scale, si) => (
          <polygon
            key={si}
            points={data.map((_, i) => pointPos(i, radius * scale).join(",")).join(" ")}
            fill="none"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="1"
          />
        ))}
        {/* 轴线 */}
        {data.map((_, i) => {
          const [x, y] = pointPos(i, radius);
          return (
            <line key={i} x1={center} y1={center} x2={x} y2={y} stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
          );
        })}
        {/* 数据填充 */}
        <polygon
          points={dataPoints}
          fill="url(#radar-grad)"
          fillOpacity="0.3"
          stroke="#a78bfa"
          strokeWidth="2"
        />
        <defs>
          <radialGradient id="radar-grad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#a78bfa" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#a78bfa" stopOpacity="0.1" />
          </radialGradient>
        </defs>
        {/* 数据点 */}
        {data.map((d, i) => {
          const [x, y] = pointPos(i, radius * d.strength);
          return <circle key={i} cx={x} cy={y} r="4" fill="#c4b5fd" />;
        })}
        {/* 标签 */}
        {data.map((d, i) => {
          const [x, y] = pointPos(i, radius + 22);
          return (
            <text
              key={i}
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-biolum-200"
              style={{ fontSize: "11px" }}
            >
              {d.name}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

// ---- 性格标签云 ----
function TraitCloud({ traits }: { traits: Array<{ word: string; weight: number }> }) {
  if (traits.length === 0) {
    return <div className="h-40 flex items-center justify-center text-biolum-300/40 text-sm">还没有足够的自我认知数据</div>;
  }

  return (
    <div className="flex flex-wrap gap-2 items-center min-h-[160px]">
      {traits.map((t, i) => {
        const size = 12 + t.weight * 18; // 12px ~ 30px
        const opacity = 0.5 + t.weight * 0.5;
        const colors = [
          "text-fuchsia-300", "text-purple-300", "text-violet-300",
          "text-biolum-200", "text-emerald-300", "text-sky-300",
        ];
        const color = colors[i % colors.length];
        return (
          <span
            key={t.word}
            className={`${color} font-medium`}
            style={{ fontSize: `${size}px`, opacity }}
          >
            {t.word}
          </span>
        );
      })}
    </div>
  );
}

// ---- 说话风格进度条 ----
function StyleBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-biolum-300/60 mb-1">
        <span>{label}</span>
        <span>{Math.round(value * 100)}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-abyss-700/50 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${value * 100}%` }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="h-full rounded-full bg-gradient-to-r from-fuchsia-500 to-purple-500"
        />
      </div>
    </div>
  );
}
