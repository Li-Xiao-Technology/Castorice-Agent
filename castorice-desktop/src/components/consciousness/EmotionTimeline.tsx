import { useEffect, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import { Heart, TrendingUp, RefreshCw, Activity } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import api from "@/services/api";
import type { EmotionHistoryPoint, EmotionState } from "@/types";
import { format, formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

function Sparkline({
  data,
  color,
  height = 60,
  min = -1,
  max = 1,
}: {
  data: number[];
  color: string;
  height?: number;
  min?: number;
  max?: number;
}) {
  if (data.length < 2) return <div style={{ height }} className="w-full" />;

  const width = 100;
  const range = max - min;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  });

  const pathD = `M ${points.join(" L ")}`;
  const areaD = `${pathD} L ${width},${height} L 0,${height} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full h-full">
      <defs>
        <linearGradient id={`grad-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#grad-${color.replace("#", "")})`} />
      <path d={pathD} fill="none" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function PADTrendChart({ history }: { history: EmotionHistoryPoint[] }) {
  const data = useMemo(() => {
    if (history.length === 0) return { p: [], a: [], d: [], labels: [] };
    const step = Math.max(1, Math.floor(history.length / 60));
    const sampled: EmotionHistoryPoint[] = [];
    for (let i = 0; i < history.length; i += step) {
      sampled.push(history[i]);
    }
    if (sampled[sampled.length - 1] !== history[history.length - 1]) {
      sampled.push(history[history.length - 1]);
    }
    return {
      p: sampled.map((h) => h.pleasure),
      a: sampled.map((h) => h.arousal),
      d: sampled.map((h) => h.dominance),
      labels: sampled.map((h) => h.timestamp),
    };
  }, [history]);

  if (history.length === 0) {
    return (
      <div className="glass rounded-xl p-8 text-center">
        <Activity className="w-8 h-8 text-biolum-300/20 mx-auto mb-3" />
        <p className="text-xs text-biolum-300/40">正在积累情绪历史数据...</p>
        <p className="text-[10px] text-biolum-300/20 mt-1">保持连接，几分钟后这里会显示情绪波动曲线</p>
      </div>
    );
  }

  const metrics = [
    { label: "愉悦度 (P)", key: "pleasure", data: data.p, color: "#f472b6" },
    { label: "唤醒度 (A)", key: "arousal", data: data.a, color: "#fbbf24" },
    { label: "支配度 (D)", key: "dominance", data: data.d, color: "#60a5fa" },
  ];

  return (
    <div className="space-y-3">
      {metrics.map((m, idx) => {
        const current = m.data[m.data.length - 1];
        const currentPct = ((current + 1) / 2) * 100;
        return (
          <div key={m.key} className="glass rounded-xl p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-medium text-biolum-200/80">{m.label}</span>
              <span className="text-[10px] font-mono" style={{ color: m.color }}>
                {current >= 0 ? "+" : ""}{current.toFixed(2)}
              </span>
            </div>
            <div className="h-14">
              <Sparkline data={m.data} color={m.color} height={56} min={-1} max={1} />
            </div>
            <div className="mt-1 h-1 bg-abyss-800 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${currentPct}%` }}
                transition={{ duration: 0.5 }}
                className="h-full rounded-full"
                style={{ backgroundColor: m.color }}
              />
            </div>
          </div>
        );
      })}
      <div className="flex items-center justify-between text-[9px] text-biolum-300/30 px-1">
        <span>
          {history.length > 0 && formatDistanceToNow(history[0].timestamp, { addSuffix: true, locale: zhCN })}
        </span>
        <span>共 {history.length} 个采样点</span>
        <span>现在</span>
      </div>
    </div>
  );
}

export default function EmotionTimeline() {
  const emotion = useAppStore((s) => s.emotion);
  const emotionHistory = useAppStore((s) => s.emotionHistory);
  const addEmotionHistoryPoint = useAppStore((s) => s.addEmotionHistoryPoint);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;

    const init = async () => {
      try {
        const e = await api.getEmotion().catch(() => null);
        if (e && e.enabled !== false) {
          addEmotionHistoryPoint({
            timestamp: Date.now(),
            pleasure: e.pleasure,
            arousal: e.arousal,
            dominance: e.dominance,
          });
        }
      } catch {
        // ignore
      }
    };
    init();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-rose-deep/20 to-rose-deep/10 border border-rose-deep/20 flex items-center justify-center">
            <Heart className="w-5 h-5 text-rose-deep" />
          </div>
          <div>
            <h2 className="font-display text-xl text-biolum-100">情绪时间线</h2>
            <p className="text-xs text-biolum-300/50">观察 Castorice 的情绪变化轨迹</p>
          </div>
        </div>
      </div>

      {/* 当前情绪速览 */}
      {emotion && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: "愉悦", value: emotion.pleasure, color: "text-rose-deep", bg: "from-rose-deep/20" },
            { label: "唤醒", value: emotion.arousal, color: "text-amber-glow", bg: "from-amber-glow/20" },
            { label: "支配", value: emotion.dominance, color: "text-blue-400", bg: "from-blue-400/20" },
            { label: "互动", value: emotion.interaction_count, suffix: "次", color: "text-biolum-300", bg: "from-biolum-500/20", isCount: true },
          ].map((item, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className={`glass rounded-xl p-3 bg-gradient-to-br ${item.bg}`}
            >
              <div className="text-[10px] text-biolum-300/50 mb-1">{item.label}</div>
              <div className={`text-xl font-display ${item.color}`}>
                {item.isCount ? item.value : `${item.value >= 0 ? "+" : ""}${item.value.toFixed(2)}`}
                {item.suffix && <span className="text-xs text-biolum-300/40 ml-0.5">{item.suffix}</span>}
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* PAD 趋势图 */}
      <PADTrendChart history={emotionHistory} />

      {/* 情绪扰动参数 */}
      {emotion && (emotion.confidence_bias || emotion.creativity_bias || emotion.patience_bias || emotion.risk_tolerance_bias) && (
        <div className="glass rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-3.5 h-3.5 text-violet-glow" />
            <span className="text-xs font-medium text-biolum-100">情绪扰动</span>
            <span className="text-[9px] text-biolum-300/40 ml-auto">当前情绪对决策的影响</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "自信心", value: emotion.confidence_bias || 0, pos: "更自信", neg: "更犹豫" },
              { label: "创造力", value: emotion.creativity_bias || 0, pos: "更发散", neg: "更收敛" },
              { label: "耐心", value: emotion.patience_bias || 0, pos: "更耐心", neg: "更急躁" },
              { label: "风险容忍", value: emotion.risk_tolerance_bias || 0, pos: "更冒险", neg: "更保守" },
            ].map((item, i) => (
              <div key={i}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-biolum-300/60">{item.label}</span>
                  <span className={`text-[9px] ${item.value >= 0 ? "text-emerald-glow" : "text-rose-deep"}`}>
                    {item.value >= 0 ? item.pos : item.neg}
                  </span>
                </div>
                <div className="h-1.5 bg-abyss-800 rounded-full overflow-hidden relative">
                  <div className="absolute left-1/2 top-0 bottom-0 w-px bg-biolum-500/20" />
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{
                      width: `${Math.abs(item.value) * 100}%`,
                      marginLeft: item.value < 0 ? `${50 - Math.abs(item.value) * 50}%` : "50%",
                    }}
                    transition={{ duration: 0.5 }}
                    className={`h-full rounded-full ${
                      item.value >= 0 ? "bg-emerald-glow/60" : "bg-rose-deep/60"
                    }`}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
