import { motion } from "framer-motion";
import { Heart, Activity } from "lucide-react";
import type { EmotionState } from "@/types";

interface Props {
  emotion?: EmotionState | null;
}

const padToPercent = (v: number) => Math.round(((v + 1) / 2) * 100);

export default function EmotionIndicator({ emotion }: Props) {
  const pleasure = emotion?.pleasure ?? 0;
  const arousal = emotion?.arousal ?? 0;
  const dominance = emotion?.dominance ?? 0;
  const enabled = emotion?.enabled ?? false;

  const getMoodLabel = () => {
    if (!enabled) return "待机";
    if (pleasure > 0.2 && arousal > 0) return "愉悦兴奋";
    if (pleasure > 0.2 && arousal <= 0) return "平静满足";
    if (pleasure < -0.2 && arousal > 0) return "焦虑紧张";
    if (pleasure < -0.2 && arousal <= 0) return "低落倦怠";
    return "中性平和";
  };

  const moodColor = () => {
    if (!enabled) return "text-biolum-300/40";
    if (pleasure > 0.2) return "text-biolum-300";
    if (pleasure < -0.2) return "text-rose-deep";
    return "text-amber-glow";
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-5 relative overflow-hidden"
    >
      {/* 背景情绪光晕 */}
      {enabled && (
        <motion.div
          animate={{
            scale: [1, 1.1, 1],
            opacity: [0.15, 0.25, 0.15],
          }}
          transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
          className={`absolute -top-10 -right-10 w-40 h-40 rounded-full blur-3xl ${
            pleasure > 0 ? "bg-biolum-500" : "bg-rose-deep"
          }`}
        />
      )}

      <div className="relative">
        <div className="flex items-center gap-2 mb-5">
          <Heart className="w-4 h-4 text-rose-deep" />
          <h3 className="font-display text-sm text-biolum-100">情感状态</h3>
        </div>

        {/* 情绪标签 */}
        <div className="text-center mb-5">
          <div className={`font-display text-3xl mb-1 ${moodColor()}`}>
            {getMoodLabel()}
          </div>
          <div className="text-[10px] text-biolum-300/40 tracking-widest uppercase">
            Current Mood
          </div>
        </div>

        {/* PAD 三维仪表 */}
        <div className="space-y-3">
          <PadBar
            label="愉悦度"
            value={pleasure}
            leftLabel="低落"
            rightLabel="愉悦"
            color="from-rose-deep via-biolum-300/50 to-biolum-300"
          />
          <PadBar
            label="唤醒度"
            value={arousal}
            leftLabel="平静"
            rightLabel="兴奋"
            color="from-biolum-300/30 via-amber-glow/60 to-amber-glow"
          />
          <PadBar
            label="支配度"
            value={dominance}
            leftLabel="顺从"
            rightLabel="主导"
            color="from-purple-400/30 via-purple-400/60 to-purple-400"
          />
        </div>
      </div>
    </motion.div>
  );
}

function PadBar({
  label,
  value,
  leftLabel,
  rightLabel,
  color,
}: {
  label: string;
  value: number;
  leftLabel: string;
  rightLabel: string;
  color: string;
}) {
  const pct = padToPercent(value);
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-biolum-300/50">{label}</span>
        <span className="text-[10px] font-mono text-biolum-300/40">
          {pct}%
        </span>
      </div>
      <div className="h-2 bg-abyss-800 rounded-full overflow-hidden relative">
        <div className="absolute inset-0 flex">
          <div className="w-1/2 h-full border-r border-biolum-500/20" />
        </div>
        <motion.div
          initial={{ width: "50%" }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={`h-full bg-gradient-to-r ${color} rounded-full`}
        />
      </div>
      <div className="flex justify-between mt-0.5">
        <span className="text-[9px] text-biolum-300/30">{leftLabel}</span>
        <span className="text-[9px] text-biolum-300/30">{rightLabel}</span>
      </div>
    </div>
  );
}
