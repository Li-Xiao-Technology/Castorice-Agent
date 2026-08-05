import { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Target, Plus, ChevronRight, ChevronDown, RefreshCw,
  Flag, CheckCircle2, Circle, Trash2, Lightbulb, CalendarDays,
  X, Sparkles, Gauge,
} from "lucide-react";
import api from "@/services/api";

type Goal = {
  id: string;
  title: string;
  description?: string;
  level: "vision" | "long_term" | "mid_term" | "action";
  status: "not_started" | "in_progress" | "completed" | "cancelled";
  progress: number;
  priority: number;
  parent_id?: string;
  motive_tags?: string[];
  milestones?: Array<{ id: string; title: string; completed: boolean; target_date?: string }>;
  target_date?: string;
  created_at: string;
  updated_at: string;
  children?: Goal[];
};

const LEVEL_LABELS: Record<string, string> = {
  vision: "愿景",
  long_term: "长期目标",
  mid_term: "中期目标",
  action: "行动项",
};
const LEVEL_COLORS: Record<string, string> = {
  vision: "from-fuchsia-500 to-purple-600",
  long_term: "from-sky-500 to-blue-600",
  mid_term: "from-emerald-500 to-teal-600",
  action: "from-amber-500 to-orange-600",
};
const LEVEL_BG: Record<string, string> = {
  vision: "bg-fuchsia-500/10 border-fuchsia-500/30 text-fuchsia-300",
  long_term: "bg-sky-500/10 border-sky-500/30 text-sky-300",
  mid_term: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  action: "bg-amber-500/10 border-amber-500/30 text-amber-300",
};
const STATUS_LABELS: Record<string, string> = {
  not_started: "未开始",
  in_progress: "进行中",
  completed: "已完成",
  cancelled: "已取消",
};

export default function GoalsPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [suggestions, setSuggestions] = useState<Array<any>>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const [formData, setFormData] = useState({
    title: "",
    description: "",
    level: "action" as Goal["level"],
    priority: 3,
    parent_id: "" as string,
    target_date: "",
    motive_tags: "" as string,
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [gRes, sRes] = await Promise.all([
        api.goals(true),
        api.goalsSuggestions(),
      ]);
      if (gRes.success) setGoals(gRes.goals || []);
      if (sRes.success) setSuggestions(sRes.suggestions || []);
    } catch (e) {
      // 静默
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleCreate = async () => {
    if (!formData.title.trim()) return;
    const payload: any = {
      title: formData.title.trim(),
      description: formData.description.trim() || undefined,
      level: formData.level,
      priority: formData.priority,
    };
    if (formData.parent_id) payload.parent_id = formData.parent_id;
    if (formData.target_date) payload.target_date = formData.target_date;
    if (formData.motive_tags.trim()) {
      payload.motive_tags = formData.motive_tags.split(/[,，\s]+/).filter(Boolean);
    }
    try {
      await api.goalsCreate(payload);
      setFormData({ title: "", description: "", level: "action", priority: 3, parent_id: "", target_date: "", motive_tags: "" });
      setShowCreate(false);
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  const handleStatusChange = async (id: string, newStatus: Goal["status"]) => {
    try {
      await api.goalsUpdate(id, { status: newStatus });
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除此目标及其所有子目标？")) return;
    try {
      await api.goalsDelete(id);
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  const handleApplySuggestion = async (s: any) => {
    try {
      await api.goalsCreate({
        title: s.title,
        description: s.description,
        level: s.level,
        priority: 3,
        motive_tags: s.motive_tags,
      });
      fetchData();
    } catch (e) {
      console.error(e);
    }
  };

  // 把目标树拍平成列表（用于 parent 选择器）
  const flattenGoals = (list: Goal[]): Goal[] => {
    let result: Goal[] = [];
    list.forEach((g) => {
      result.push(g);
      if (g.children) result = result.concat(flattenGoals(g.children));
    });
    return result;
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center shadow-glow">
              <Target className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
            </div>
            <div>
              <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">目标管理</h1>
              <p className="text-sm text-biolum-300/50 mt-0.5">愿景 → 长期 → 中期 → 行动，层层递进</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchData}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 rounded-xl bg-abyss-800/50 border border-biolum-500/20 hover:border-biolum-500/40 transition-all text-sm text-biolum-200"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 transition-all text-sm font-medium text-abyss-950 shadow-glow"
            >
              <Plus className="w-4 h-4" />
              新目标
            </button>
          </div>
        </div>

        {/* 层级说明 */}
        <div className="flex flex-wrap gap-2">
          {Object.entries(LEVEL_LABELS).map(([k, v]) => (
            <span key={k} className={`text-xs px-2.5 py-1 rounded-lg border ${LEVEL_BG[k]}`}>{v}</span>
          ))}
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 目标树（左 2/3） */}
          <div className="lg:col-span-2">
            <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
              <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
                <Flag className="w-4 h-4 text-biolum-400" />
                目标树
              </h3>
              {goals.length === 0 ? (
                <div className="py-16 text-center">
                  <Target className="w-12 h-12 text-biolum-300/20 mx-auto mb-3" />
                  <p className="text-biolum-300/40 text-sm mb-4">还没有设定任何目标</p>
                  <button
                    onClick={() => setShowCreate(true)}
                    className="text-sm text-amber-400 hover:text-amber-300"
                  >
                    创建第一个目标 →
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {goals.map((g) => (
                    <GoalNode
                      key={g.id}
                      goal={g}
                      level={0}
                      expandedIds={expandedIds}
                      onToggle={toggleExpand}
                      onStatusChange={handleStatusChange}
                      onDelete={handleDelete}
                      onAddMilestone={(id, title) => api.goalsAddMilestone(id, { title }).then(fetchData)}
                      onCompleteMilestone={(gid, msid) => api.goalsCompleteMilestone(gid, msid).then(fetchData)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* 右侧：建议 */}
          <div>
            <div className="rounded-2xl bg-abyss-800/30 border border-biolum-500/10 p-5">
              <h3 className="font-semibold text-biolum-100 mb-4 flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-amber-400" />
                AI 目标建议
              </h3>
              {suggestions.length === 0 ? (
                <p className="text-biolum-300/40 text-sm">暂无建议，多与 Agent 互动以生成个性化目标</p>
              ) : (
                <div className="space-y-2">
                  {suggestions.map((s, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, x: 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="rounded-xl bg-abyss-900/50 border border-biolum-500/10 p-3 hover:border-amber-500/30 transition-all"
                    >
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <h4 className="font-medium text-biolum-100 text-sm">{s.title}</h4>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${LEVEL_BG[s.level] || LEVEL_BG.action}`}>
                          {LEVEL_LABELS[s.level] || "行动"}
                        </span>
                      </div>
                      {s.description && <p className="text-xs text-biolum-300/50 mb-2">{s.description}</p>}
                      {s.reason && <p className="text-[10px] text-biolum-300/30 italic">💡 {s.reason}</p>}
                      {s.motive_tags && s.motive_tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {s.motive_tags.map((t: string) => (
                            <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-biolum-500/10 text-biolum-300/60">#{t}</span>
                          ))}
                        </div>
                      )}
                      <button
                        onClick={() => handleApplySuggestion(s)}
                        className="mt-2 text-xs text-amber-400 hover:text-amber-300"
                      >
                        + 添加为目标
                      </button>
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 创建弹窗 */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-abyss-950/70 backdrop-blur-sm"
            onClick={() => setShowCreate(false)}
          >
            <motion.div
              initial={{ scale: 0.95, y: 10 }}
              animate={{ scale: 1, y: 0 }}
              exit={{ scale: 0.95, y: 10 }}
              className="w-full max-w-lg rounded-2xl bg-abyss-900 border border-biolum-500/20 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-5 py-4 border-b border-biolum-500/10">
                <h3 className="font-semibold text-biolum-100 flex items-center gap-2">
                  <Plus className="w-4 h-4 text-amber-400" />
                  创建目标
                </h3>
                <button onClick={() => setShowCreate(false)} className="text-biolum-300/50 hover:text-biolum-200">
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="p-5 space-y-4">
                <div>
                  <label className="text-xs text-biolum-300/60 mb-1.5 block">标题 *</label>
                  <input
                    value={formData.title}
                    onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                    placeholder="要达成什么？"
                    className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100 placeholder:text-biolum-300/30"
                  />
                </div>

                <div>
                  <label className="text-xs text-biolum-300/60 mb-1.5 block">描述</label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="更详细地描述这个目标..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100 placeholder:text-biolum-300/30 resize-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-biolum-300/60 mb-1.5 block">层级</label>
                    <select
                      value={formData.level}
                      onChange={(e) => setFormData({ ...formData, level: e.target.value as any })}
                      className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100"
                    >
                      {Object.entries(LEVEL_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-biolum-300/60 mb-1.5 block">优先级 ({formData.priority})</label>
                    <input
                      type="range"
                      min={1}
                      max={5}
                      value={formData.priority}
                      onChange={(e) => setFormData({ ...formData, priority: Number(e.target.value) })}
                      className="w-full accent-amber-500"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-biolum-300/60 mb-1.5 block">父目标</label>
                    <select
                      value={formData.parent_id}
                      onChange={(e) => setFormData({ ...formData, parent_id: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100"
                    >
                      <option value="">无（顶层目标）</option>
                      {flattenGoals(goals).map((g) => (
                        <option key={g.id} value={g.id}>{LEVEL_LABELS[g.level]}: {g.title}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-biolum-300/60 mb-1.5 block flex items-center gap-1">
                      <CalendarDays className="w-3 h-3" /> 目标日期
                    </label>
                    <input
                      type="date"
                      value={formData.target_date}
                      onChange={(e) => setFormData({ ...formData, target_date: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs text-biolum-300/60 mb-1.5 block flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> 动机标签（逗号分隔）
                  </label>
                  <input
                    value={formData.motive_tags}
                    onChange={(e) => setFormData({ ...formData, motive_tags: e.target.value })}
                    placeholder="求知, 创造, 社交..."
                    className="w-full px-3 py-2 rounded-lg bg-abyss-800/50 border border-biolum-500/15 focus:border-amber-500/50 focus:outline-none text-sm text-biolum-100 placeholder:text-biolum-300/30"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-biolum-500/10">
                <button
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2 rounded-lg text-sm text-biolum-300/70 hover:text-biolum-100"
                >
                  取消
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!formData.title.trim()}
                  className="px-4 py-2 rounded-lg bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-400 hover:to-orange-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium text-abyss-950"
                >
                  创建
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---- 目标节点（递归）----
function GoalNode({
  goal, level, expandedIds, onToggle, onStatusChange, onDelete,
  onAddMilestone, onCompleteMilestone,
}: {
  goal: Goal; level: number; expandedIds: Set<string>;
  onToggle: (id: string) => void;
  onStatusChange: (id: string, status: Goal["status"]) => void;
  onDelete: (id: string) => void;
  onAddMilestone: (id: string, title: string) => void;
  onCompleteMilestone: (gid: string, msid: string) => void;
}) {
  const [showMsInput, setShowMsInput] = useState(false);
  const [msTitle, setMsTitle] = useState("");
  const hasChildren = goal.children && goal.children.length > 0;
  const isExpanded = expandedIds.has(goal.id);

  const statusColor = {
    not_started: "text-biolum-300/40",
    in_progress: "text-amber-400",
    completed: "text-emerald-400",
    cancelled: "text-rose-400",
  }[goal.status];

  return (
    <div>
      <motion.div
        layout
        className="rounded-xl bg-abyss-900/40 border border-biolum-500/10 hover:border-biolum-500/20 transition-all"
        style={{ marginLeft: level * 16 }}
      >
        <div className="flex items-start gap-2 p-3">
          {/* 展开 */}
          {hasChildren ? (
            <button onClick={() => onToggle(goal.id)} className="mt-0.5 text-biolum-300/40 hover:text-biolum-200">
              {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          ) : (
            <div className="w-4" />
          )}

          {/* 状态切换 */}
          <button
            onClick={() => {
              const next: Record<string, Goal["status"]> = {
                not_started: "in_progress",
                in_progress: "completed",
                completed: "not_started",
                cancelled: "not_started",
              };
              onStatusChange(goal.id, next[goal.status]);
            }}
            className={`mt-0.5 ${statusColor} hover:scale-110 transition-transform`}
          >
            {goal.status === "completed" ? (
              <CheckCircle2 className="w-5 h-5" />
            ) : (
              <Circle className="w-5 h-5" />
            )}
          </button>

          {/* 内容 */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h4 className={`font-medium text-sm ${goal.status === "completed" ? "text-biolum-300/40 line-through" : "text-biolum-100"}`}>
                {goal.title}
              </h4>
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${LEVEL_BG[goal.level]}`}>{LEVEL_LABELS[goal.level]}</span>
              <span className={`text-[10px] ${statusColor}`}>{STATUS_LABELS[goal.status]}</span>
              {/* 优先级点 */}
              <div className="flex gap-0.5">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div
                    key={i}
                    className={`w-1.5 h-1.5 rounded-full ${i < goal.priority ? "bg-amber-400" : "bg-biolum-300/10"}`}
                  />
                ))}
              </div>
            </div>

            {goal.description && (
              <p className="text-xs text-biolum-300/50 mt-1">{goal.description}</p>
            )}

            {/* 进度条 */}
            <div className="mt-2">
              <div className="flex justify-between text-[10px] text-biolum-300/40 mb-0.5">
                <span className="flex items-center gap-1"><Gauge className="w-3 h-3" />进度</span>
                <span>{Math.round(goal.progress * 100)}%</span>
              </div>
              <div className="h-1 rounded-full bg-abyss-700/50 overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${goal.progress * 100}%` }}
                  className={`h-full rounded-full bg-gradient-to-r ${LEVEL_COLORS[goal.level]}`}
                />
              </div>
            </div>

            {/* 标签 */}
            {goal.motive_tags && goal.motive_tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {goal.motive_tags.map((t) => (
                  <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-biolum-500/10 text-biolum-300/50">#{t}</span>
                ))}
              </div>
            )}

            {/* 里程碑 */}
            {goal.milestones && goal.milestones.length > 0 && (
              <div className="mt-2 space-y-1">
                {goal.milestones.map((ms) => (
                  <div key={ms.id} className="flex items-center gap-2 text-xs">
                    <button onClick={() => onCompleteMilestone(goal.id, ms.id)}>
                      {ms.completed ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <Circle className="w-3.5 h-3.5 text-biolum-300/30" />
                      )}
                    </button>
                    <span className={ms.completed ? "text-biolum-300/40 line-through" : "text-biolum-200/80"}>{ms.title}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 加里程碑 */}
            <div className="mt-2">
              {showMsInput ? (
                <div className="flex gap-2">
                  <input
                    value={msTitle}
                    onChange={(e) => setMsTitle(e.target.value)}
                    placeholder="里程碑标题..."
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && msTitle.trim()) {
                        onAddMilestone(goal.id, msTitle.trim());
                        setMsTitle("");
                        setShowMsInput(false);
                      }
                    }}
                    autoFocus
                    className="flex-1 px-2 py-1 rounded bg-abyss-800/50 border border-biolum-500/15 text-xs text-biolum-100 focus:outline-none focus:border-amber-500/50"
                  />
                  <button onClick={() => { setShowMsInput(false); setMsTitle(""); }} className="text-xs text-biolum-300/50">取消</button>
                </div>
              ) : (
                <button
                  onClick={() => setShowMsInput(true)}
                  className="text-[10px] text-biolum-300/40 hover:text-amber-400 flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> 添加里程碑
                </button>
              )}
            </div>
          </div>

          {/* 删除 */}
          <button
            onClick={() => onDelete(goal.id)}
            className="text-biolum-300/20 hover:text-rose-400 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </motion.div>

      {/* 子目标 */}
      <AnimatePresence>
        {hasChildren && isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-2">
              {goal.children!.map((child) => (
                <GoalNode
                  key={child.id}
                  goal={child}
                  level={level + 1}
                  expandedIds={expandedIds}
                  onToggle={onToggle}
                  onStatusChange={onStatusChange}
                  onDelete={onDelete}
                  onAddMilestone={onAddMilestone}
                  onCompleteMilestone={onCompleteMilestone}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
