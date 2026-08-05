import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { User, Sparkles, RefreshCw, BookOpen, Shield, Clock, FileText, Heart, Users } from "lucide-react";
import api from "@/services/api";
import { useAppStore } from "@/stores/appStore";
import type { SelfConcept as SelfConceptType, SelfNarrativeEvent } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

function parseSelfConcept(raw: any): SelfConceptType {
  const result: SelfConceptType = {
    enabled: raw?.enabled ?? false,
    content: raw?.content || "",
  };

  if (!result.content) return result;

  const sections: Record<string, string> = {};
  let currentKey = "";
  let currentVal: string[] = [];

  const lines = result.content.split("\n");
  for (const line of lines) {
    const headerMatch = line.match(/^#+\s*(.+?)\s*#*$/);
    if (headerMatch) {
      if (currentKey) sections[currentKey] = currentVal.join("\n").trim();
      currentKey = headerMatch[1].trim();
      currentVal = [];
    } else {
      currentVal.push(line);
    }
  }
  if (currentKey) sections[currentKey] = currentVal.join("\n").trim();

  const findSection = (keywords: string[]) => {
    for (const key of Object.keys(sections)) {
      const lowerKey = key.toLowerCase();
      if (keywords.some((k) => lowerKey.includes(k))) return sections[key];
    }
    return "";
  };

  // 获取"我的自我概念"这个主章节的全部内容（没有子章节时的兜底）
  const mainSection =
    findSection(["我的自我概念", "自我概念", "self concept"]) ||
    Object.values(sections).join("\n\n").trim();

  // 按 --- 分隔符切分成不同段落，取最后几段作为"近期"内容
  const paragraphs = result.content
    .split(/\n---\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 20);
  const recentParagraphs = paragraphs.slice(-3).join("\n\n");

  result.core_self = {
    identity:
      findSection(["身份", "identity", "我是谁", "核心身份"]) ||
      findSection(["核心"]) ||
      mainSection.slice(0, 500),
    values: findSection(["价值", "value", "信仰", "原则"]),
    capabilities: findSection(["能力", "capability", "skill", "擅长"]),
    traits: findSection(["性格", "trait", "特质", "personality"]),
  };

  result.narrative_self = {
    current_mood: findSection(["情绪", "mood", "心情", "感受"]),
    current_goals: findSection(["目标", "goal", "想做", "计划"]),
    relationship_status: findSection(["关系", "relation", "社交", "朋友"]),
    recent_experiences:
      findSection(["经历", "experience", "最近", "近期"]) || recentParagraphs,
  };

  return result;
}

const sectionIcons: Record<string, any> = {
  identity: User,
  values: Shield,
  capabilities: Sparkles,
  traits: BookOpen,
  current_mood: Heart,
  current_goals: FileText,
  relationship_status: Users,
  recent_experiences: Clock,
};

export default function SelfConceptPanel() {
  const selfConcept = useAppStore((s) => s.selfConcept);
  const setSelfConcept = useAppStore((s) => s.setSelfConcept);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await api.getSelfConcept();
      const parsed = parseSelfConcept(res);
      setSelfConcept(parsed);
    } catch (e) {
      console.warn("加载自我概念失败", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const coreSelf = selfConcept?.core_self;
  const narrativeSelf = selfConcept?.narrative_self;
  const hasCore = coreSelf && Object.values(coreSelf).some((v) => v?.trim());
  const hasNarrative = narrativeSelf && Object.values(narrativeSelf).some((v) => v?.trim());

  const coreFields = [
    { key: "identity", label: "核心身份" },
    { key: "values", label: "价值观" },
    { key: "capabilities", label: "能力认知" },
    { key: "traits", label: "性格特质" },
  ];

  const narrativeFields = [
    { key: "current_mood", label: "当前情绪" },
    { key: "current_goals", label: "当前目标" },
    { key: "relationship_status", label: "关系状态" },
    { key: "recent_experiences", label: "近期经历" },
  ];

  return (
    <div className="space-y-6">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-glow/20 to-violet-glow/10 border border-violet-glow/20 flex items-center justify-center">
            <User className="w-5 h-5 text-violet-glow" />
          </div>
          <div>
            <h2 className="font-display text-xl text-biolum-100">自我认知</h2>
            <p className="text-xs text-biolum-300/50">
              Castorice 如何看待它自己——核心特质与当下状态
            </p>
          </div>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="glass rounded-lg px-3 py-2 text-xs text-biolum-300/70 hover:text-biolum-200 transition-colors flex items-center gap-2"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {loading && !selfConcept ? (
        <div className="glass rounded-2xl p-12 text-center">
          <div className="w-8 h-8 border-2 border-biolum-500/20 border-t-biolum-400 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-xs text-biolum-300/50">正在读取自我认知...</p>
        </div>
      ) : !selfConcept?.enabled || !selfConcept?.content ? (
        <div className="glass rounded-2xl p-12 text-center">
          <User className="w-10 h-10 text-biolum-300/20 mx-auto mb-4" />
          <p className="text-sm text-biolum-300/50 mb-2">自我概念尚未初始化</p>
          <p className="text-xs text-biolum-300/30">随着与 Agent 的交互，它会逐渐形成对自己的认知</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* 核心自我 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="glass rounded-2xl p-5 border border-violet-glow/10"
          >
            <div className="flex items-center gap-2 mb-5">
              <Shield className="w-4 h-4 text-violet-glow" />
              <h3 className="font-display text-sm text-biolum-100">核心自我</h3>
              <span className="text-[9px] text-biolum-300/40 ml-auto">稳定 · 变化缓慢</span>
            </div>
            <div className="space-y-4">
              {hasCore ? (
                coreFields.map((field) => {
                  const value = (coreSelf as any)[field.key];
                  if (!value?.trim()) return null;
                  return (
                    <div key={field.key} className="bg-abyss-800/40 rounded-xl p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[10px] text-violet-glow/80 font-medium">{field.label}</span>
                      </div>
                      <p className="text-xs text-biolum-200/70 leading-relaxed whitespace-pre-wrap">{value}</p>
                    </div>
                  );
                })
              ) : (
                <div className="text-center py-8">
                  <p className="text-xs text-biolum-300/30">核心自我正在形成中...</p>
                </div>
              )}
            </div>
          </motion.div>

          {/* 叙事自我 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="glass rounded-2xl p-5 border border-rose-deep/10"
          >
            <div className="flex items-center gap-2 mb-5">
              <Sparkles className="w-4 h-4 text-rose-deep" />
              <h3 className="font-display text-sm text-biolum-100">叙事自我</h3>
              <span className="text-[9px] text-biolum-300/40 ml-auto">动态 · 反映当下</span>
            </div>
            <div className="space-y-4">
              {hasNarrative ? (
                narrativeFields.map((field) => {
                  const value = (narrativeSelf as any)[field.key];
                  if (!value?.trim()) return null;
                  return (
                    <div key={field.key} className="bg-abyss-800/40 rounded-xl p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[10px] text-rose-deep/80 font-medium">{field.label}</span>
                      </div>
                      <p className="text-xs text-biolum-200/70 leading-relaxed whitespace-pre-wrap">{value}</p>
                    </div>
                  );
                })
              ) : (
                <div className="text-center py-8">
                  <p className="text-xs text-biolum-300/30">叙事自我正在更新中...</p>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
