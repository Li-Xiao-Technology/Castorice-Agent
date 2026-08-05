import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Database,
  HardDrive,
  Clock,
  Search,
  Trash2,
  BookOpen,
  Brain,
  AlertTriangle,
  Check,
} from "lucide-react";
import SettingCard from "./SettingCard";
import SettingRow from "./SettingRow";
import Toggle from "./Toggle";
import Slider from "./Slider";
import api from "@/services/api";

export default function MemorySettings() {
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [data, st] = await Promise.all([
          api.getSettings(),
          api.status().catch(() => null),
        ]);
        setSettings(data);
        setStatus(st);
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
      <div className="space-y-5">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="glass rounded-2xl p-6 animate-pulse"
          >
            <div className="h-6 w-40 bg-biolum-500/10 rounded mb-4" />
            <div className="h-4 w-full bg-biolum-500/10 rounded mb-2" />
            <div className="h-4 w-3/4 bg-biolum-500/10 rounded" />
          </div>
        ))}
      </div>
    );
  }

  const memory = settings.memory || {};
  const shortTerm = memory.short_term || {};
  const longTerm = memory.long_term || {};
  const skill = memory.skill || {};

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-5"
    >
      {/* 存储概览 */}
      <SettingCard
        title="存储概览"
        description="各类记忆的当前使用状态"
        icon={<Database className="w-4 h-4 text-biolum-300" />}
      >
        <div className="grid grid-cols-2 gap-4">
          <StatItem
            label="会话数"
            value={status?.sessions_count ?? "—"}
            icon={<Clock className="w-3.5 h-3.5" />}
          />
          <StatItem
            label="技能数"
            value={status?.skills_count ?? "—"}
            icon={<BookOpen className="w-3.5 h-3.5" />}
          />
          <StatItem
            label="长期记忆"
            value={
              status?.long_term_available
                ? `${status?.long_term_count ?? 0} 条`
                : "未启用"
            }
            icon={<Brain className="w-3.5 h-3.5" />}
            muted={!status?.long_term_available}
          />
          <StatItem
            label="总调用"
            value={status?.total_calls ?? "—"}
            icon={<HardDrive className="w-3.5 h-3.5" />}
          />
        </div>
      </SettingCard>

      {/* 短期记忆 */}
      <SettingCard
        title="短期记忆"
        description="会话内的对话历史存储"
        icon={<Clock className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="最大保留轮数"
          description="每个会话最多保留的对话轮数"
        >
          <div className="w-56">
            <Slider
              value={shortTerm.max_turns ?? 20}
              min={5}
              max={100}
              step={5}
              onChange={() => {}}
              unit=" 轮"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="存储路径"
          description="SQLite 数据库文件位置"
        >
          <code className="text-[10px] font-mono text-biolum-300/60 bg-abyss-900/50 px-2 py-1 rounded">
            {shortTerm.db_path || "./castorice_data/sessions.db"}
          </code>
        </SettingRow>
      </SettingCard>

      {/* 长期记忆 */}
      <SettingCard
        title="长期记忆"
        description="跨会话的知识与经验持久化"
        icon={<Brain className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="记忆后端"
          description="长期记忆的存储引擎"
        >
          <select
            defaultValue={memory.backend || "chroma"}
            className="bg-abyss-900/60 border border-biolum-500/20 rounded-lg px-3 py-1.5 text-sm text-biolum-100 focus:outline-none focus:border-biolum-500/50"
          >
            <option value="chroma">ChromaDB（本地）</option>
            <option value="faiss">FAISS（本地）</option>
            <option value="pinecone">Pinecone（云端）</option>
          </select>
        </SettingRow>
        <SettingRow
          label="检索返回条数"
          description="每次记忆检索最多返回的条目"
        >
          <div className="w-56">
            <Slider
              value={longTerm.top_k ?? 5}
              min={1}
              max={20}
              step={1}
              onChange={() => {}}
              unit=" 条"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="相似度阈值"
          description="低于此阈值的记忆将被过滤"
        >
          <div className="w-56">
            <Slider
              value={longTerm.similarity_threshold ?? 0.75}
              min={0.3}
              max={1.0}
              step={0.05}
              onChange={() => {}}
              displayValue={(longTerm.similarity_threshold ?? 0.75).toFixed(2)}
            />
          </div>
        </SettingRow>
        {status?.long_term_available === false && (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-amber-glow/10 border border-amber-glow/20">
            <AlertTriangle className="w-4 h-4 text-amber-glow shrink-0" />
            <div className="text-xs text-amber-soft/80">
              长期记忆未启用，请安装依赖：
              <code className="ml-1 text-amber-soft">
                pip install chromadb sentence-transformers
              </code>
            </div>
          </div>
        )}
      </SettingCard>

      {/* 技能记忆 */}
      <SettingCard
        title="技能记忆"
        description="Agent 自动沉淀的可复用技能"
        icon={<BookOpen className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="自动生成技能"
          description="根据对话历史自动发现可复用模式"
        >
          <Toggle checked={skill.auto_generate ?? true} onChange={() => {}} />
        </SettingRow>
        <SettingRow
          label="触发次数阈值"
          description="模式出现多少次后才生成技能"
        >
          <div className="w-56">
            <Slider
              value={skill.min_trigger_count ?? 3}
              min={1}
              max={10}
              step={1}
              onChange={() => {}}
              unit=" 次"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="版本控制"
          description="保留技能的历史版本"
        >
          <Toggle checked={skill.version_control ?? true} onChange={() => {}} />
        </SettingRow>
      </SettingCard>

      {/* 记忆搜索 */}
      <SettingCard
        title="记忆搜索"
        description="在长期记忆中检索相关内容"
        icon={<Search className="w-4 h-4 text-biolum-300" />}
      >
        <MemorySearch />
      </SettingCard>

      {/* 危险操作 */}
      <SettingCard
        title="数据管理"
        description="谨慎操作，数据删除后无法恢复"
        icon={<Trash2 className="w-4 h-4 text-rose-deep" />}
      >
        <SettingRow
          label="清除当前会话记忆"
          description="移除当前会话的所有上下文"
        >
          <button
            onClick={async () => {
              if (confirm("确定要清除当前会话记忆吗？")) {
                try {
                  await api.clearMemory();
                  alert("已清除");
                } catch (e) {
                  alert("清除失败");
                }
              }
            }}
            className="px-3 py-1.5 rounded-lg text-xs bg-rose-deep/10 text-rose-deep border border-rose-deep/20 hover:bg-rose-deep/20 transition"
          >
            清除
          </button>
        </SettingRow>
      </SettingCard>
    </motion.div>
  );
}

function StatItem({
  label,
  value,
  icon,
  muted = false,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="p-3 rounded-xl bg-abyss-900/40 border border-biolum-500/10">
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className={muted ? "text-biolum-300/30" : "text-biolum-400"}
        >
          {icon}
        </span>
        <span className="text-[11px] text-biolum-300/50">{label}</span>
      </div>
      <div
        className={`text-lg font-display ${
          muted ? "text-biolum-300/30" : "text-biolum-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function MemorySearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  const doSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const data = await api.searchMemory(query, 10);
      setResults(data.results || []);
    } catch (e) {
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div>
      <div className="flex gap-2 mb-3">
        <input
          type="text"
          placeholder="搜索记忆内容..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          className="flex-1 bg-abyss-900/60 border border-biolum-500/20 rounded-lg px-3 py-2 text-sm text-biolum-100 placeholder-biolum-300/30 focus:outline-none focus:border-biolum-500/50"
        />
        <button
          onClick={doSearch}
          disabled={searching}
          className="px-4 py-2 rounded-lg bg-biolum-500/15 text-biolum-100 border border-biolum-500/30 text-sm hover:bg-biolum-500/25 transition disabled:opacity-50"
        >
          {searching ? "..." : "搜索"}
        </button>
      </div>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {results.length === 0 && !searching && (
          <p className="text-xs text-biolum-300/40 text-center py-4">
            输入关键词搜索长期记忆
          </p>
        )}
        {results.map((r, i) => (
          <div
            key={i}
            className="p-3 rounded-lg bg-abyss-900/40 border border-biolum-500/10"
          >
            <div className="flex items-center gap-2 mb-1">
              <Check className="w-3 h-3 text-biolum-400" />
              <span className="text-[10px] font-mono text-biolum-300/50">
                相似度: {(r.score ?? r.similarity ?? 0).toFixed(3)}
              </span>
            </div>
            <p className="text-xs text-biolum-200/80 line-clamp-2">
              {r.content || r.text || r.document || JSON.stringify(r)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
