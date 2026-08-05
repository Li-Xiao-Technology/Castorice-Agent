import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Brain, Sparkles, Heart, Zap, MessageCircle, Clock, Bell, Users } from "lucide-react";
import SettingCard from "./SettingCard";
import SettingRow from "./SettingRow";
import Toggle from "./Toggle";
import Slider from "./Slider";
import api from "@/services/api";
import { useAppStore } from "@/stores/appStore";

export default function AgentSettings() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.getSettings();
        setSettings(data);
      } catch (e) {
        // 静默
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading || !settings) {
    return (
      <div className="glass rounded-2xl p-6 animate-pulse">
        <div className="h-6 w-40 bg-biolum-500/10 rounded mb-4" />
        <div className="h-4 w-full bg-biolum-500/10 rounded mb-2" />
        <div className="h-4 w-3/4 bg-biolum-500/10 rounded" />
      </div>
    );
  }

  const runtime = settings.runtime || {};
  const consciousness = runtime.consciousness || {};
  const autonomous = runtime.autonomous || {};
  const emotion = runtime.emotion || {};
  const agent = settings.agent || {};

  const updateField = (path: string, value: any) => {
    setSettings((prev: any) => {
      const next = JSON.parse(JSON.stringify(prev));
      const keys = path.split(".");
      let cur = next;
      for (let i = 0; i < keys.length - 1; i++) {
        if (!cur[keys[i]]) cur[keys[i]] = {};
        cur = cur[keys[i]];
      }
      cur[keys[keys.length - 1]] = value;
      return next;
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-5"
    >
      {/* 基本信息 */}
      <SettingCard
        title="基本身份"
        description="Agent 的显示名称和角色设定"
        icon={<Brain className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow label="Agent 名称" description="显示在界面上的名字">
          <input
            type="text"
            defaultValue={agent.name || "Castorice"}
            className="bg-abyss-900/60 border border-biolum-500/20 rounded-lg px-3 py-1.5 text-sm text-biolum-100 focus:outline-none focus:border-biolum-500/50 w-48"
          />
        </SettingRow>
        <SettingRow label="角色描述" description="Agent 的自我定位">
          <input
            type="text"
            defaultValue={agent.role || "自进化个人智能体"}
            className="bg-abyss-900/60 border border-biolum-500/20 rounded-lg px-3 py-1.5 text-sm text-biolum-100 focus:outline-none focus:border-biolum-500/50 w-48"
          />
        </SettingRow>
      </SettingCard>

      {/* 意识引擎 */}
      <SettingCard
        title="意识引擎"
        description="持续内在思维流与主动对话能力"
        icon={<Sparkles className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="启用意识引擎"
          description="让 Agent 拥有持续的内在思维活动"
        >
          <Toggle
            checked={consciousness.enabled ?? true}
            onChange={(v) => updateField("runtime.consciousness.enabled", v)}
          />
        </SettingRow>
        <SettingRow
          label="主动说话"
          description="允许 Agent 在有重要想法时主动发起对话"
        >
          <Toggle
            checked={consciousness.speak_enabled ?? true}
            onChange={(v) => updateField("runtime.consciousness.speak_enabled", v)}
          />
        </SettingRow>
        <SettingRow
          label="后台思考间隔（秒）"
          description="你不说话时，Agent 多久产生一个念头"
        >
          <div className="w-56">
            <Slider
              value={consciousness.background_interval_min ?? 10}
              min={5}
              max={120}
              step={5}
              onChange={(v) => updateField("runtime.consciousness.background_interval_min", v)}
              unit="s"
              labels={["频繁", "适中", "悠闲"]}
            />
          </div>
        </SettingRow>
        <SettingRow
          label="空闲切换阈值（秒）"
          description="多久没说话后切换到后台思考模式"
        >
          <div className="w-56">
            <Slider
              value={consciousness.idle_threshold_seconds ?? 180}
              min={30}
              max={600}
              step={30}
              onChange={(v) => updateField("runtime.consciousness.idle_threshold_seconds", v)}
              unit="s"
            />
          </div>
        </SettingRow>
      </SettingCard>

      {/* 自主循环 */}
      <SettingCard
        title="自主循环"
        description="空闲时自动进行反思、巡查、探索"
        icon={<Zap className="w-4 h-4 text-amber-glow" />}
      >
        <SettingRow
          label="启用自主循环"
          description="你不在时 Agent 自己运转"
        >
          <Toggle
            checked={autonomous.enabled ?? true}
            onChange={(v) => updateField("runtime.autonomous.enabled", v)}
          />
        </SettingRow>
        <SettingRow
          label="唤醒间隔（秒）"
          description="深度思考的执行频率"
        >
          <div className="w-56">
            <Slider
              value={autonomous.interval_seconds ?? 120}
              min={60}
              max={3600}
              step={60}
              onChange={(v) => updateField("runtime.autonomous.interval_seconds", v)}
              unit="s"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="快速响应间隔（秒）"
          description="检查私信和即时事务的频率"
        >
          <div className="w-56">
            <Slider
              value={autonomous.quick_interval_seconds ?? 45}
              min={15}
              max={300}
              step={15}
              onChange={(v) => updateField("runtime.autonomous.quick_interval_seconds", v)}
              unit="s"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="用户空闲阈值（秒）"
          description="你多久没说话后才启动深度思考"
        >
          <div className="w-56">
            <Slider
              value={autonomous.idle_threshold_seconds ?? 60}
              min={30}
              max={1800}
              step={30}
              onChange={(v) => updateField("runtime.autonomous.idle_threshold_seconds", v)}
              unit="s"
            />
          </div>
        </SettingRow>
      </SettingCard>

      {/* 情感引擎 */}
      <SettingCard
        title="情感引擎"
        description="Agent 的情绪状态与人格表达"
        icon={<Heart className="w-4 h-4 text-rose-deep" />}
      >
        <SettingRow
          label="启用情感系统"
          description="让 Agent 拥有情绪波动和情感表达"
        >
          <Toggle
            checked={emotion.enabled ?? true}
            onChange={(v) => updateField("runtime.emotion.enabled", v)}
          />
        </SettingRow>
        <SettingRow
          label="当前情绪状态"
          description="实时 PAD 情绪维度"
        >
          <EmotionStatus />
        </SettingRow>
      </SettingCard>

      {/* 行为偏好 */}
      <SettingCard
        title="行为偏好"
        description="Agent 的执行风格和决策倾向"
        icon={<MessageCircle className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="执行模式"
          description="预设工作流 vs 自主思考"
        >
          <select
            defaultValue={runtime.agent_mode || "thinking"}
            className="bg-abyss-900/60 border border-biolum-500/20 rounded-lg px-3 py-1.5 text-sm text-biolum-100 focus:outline-none focus:border-biolum-500/50"
          >
            <option value="legacy">预设工作流（稳定）</option>
            <option value="thinking">自主思考（灵活）</option>
          </select>
        </SettingRow>
        <SettingRow
          label="启用反思"
          description="任务完成后自动复盘"
        >
          <Toggle
            checked={runtime.enable_reflection ?? true}
            onChange={(v) => updateField("runtime.enable_reflection", v)}
          />
        </SettingRow>
        <SettingRow
          label="启用自我进化"
          description="自动生成技能和沉淀经验"
        >
          <Toggle
            checked={runtime.enable_skill_generation ?? true}
            onChange={(v) => updateField("runtime.enable_skill_generation", v)}
          />
        </SettingRow>
      </SettingCard>

      {/* 通知设置 */}
      <SettingCard
        title="通知与提醒"
        description="Agent 主动联系你的方式"
        icon={<Bell className="w-4 h-4 text-violet-glow" />}
      >
        <SettingRow
          label="桌面通知"
          description="Agent 有话想说时弹出桌面通知"
        >
          <Toggle
            checked={true}
            onChange={(v) => {
              const { setNotificationsEnabled } = useAppStore.getState();
              setNotificationsEnabled(v);
            }}
          />
        </SettingRow>
        <SettingRow
          label="重要性阈值"
          description="只有超过这个重要性的想法才会通知你"
        >
          <div className="w-56">
            <Slider
              value={0.6}
              min={0}
              max={1}
              step={0.1}
              onChange={() => {}}
              unit=""
              labels={["随意", "适中", "重要"]}
            />
          </div>
        </SettingRow>
      </SettingCard>
    </motion.div>
  );
}

function EmotionStatus() {
  const [emotion, setEmotion] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await api.getEmotion();
        setEmotion(data);
      } catch (e) {
        // 静默
      }
    };
    load();
  }, []);

  if (!emotion || emotion.enabled === false) {
    return <span className="text-xs text-biolum-300/40">未启用</span>;
  }

  const p = emotion.pleasure ?? 0;
  const a = emotion.arousal ?? 0;
  const d = emotion.dominance ?? 0;

  const padColor = (v: number) =>
    v > 0.3 ? "text-biolum-300" : v < -0.3 ? "text-rose-deep" : "text-biolum-200/60";

  return (
    <div className="flex gap-3 text-xs font-mono">
      <div className="flex flex-col items-center">
        <span className="text-biolum-300/50 mb-1">愉悦</span>
        <span className={padColor(p)}>{p.toFixed(2)}</span>
      </div>
      <div className="flex flex-col items-center">
        <span className="text-biolum-300/50 mb-1">唤醒</span>
        <span className={padColor(a)}>{a.toFixed(2)}</span>
      </div>
      <div className="flex flex-col items-center">
        <span className="text-biolum-300/50 mb-1">支配</span>
        <span className={padColor(d)}>{d.toFixed(2)}</span>
      </div>
    </div>
  );
}
