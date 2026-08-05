import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Shield,
  Lock,
  Box,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Save,
  Trash2,
  Clock,
} from "lucide-react";
import SettingCard from "./SettingCard";
import SettingRow from "./SettingRow";
import Toggle from "./Toggle";
import Slider from "./Slider";
import api from "@/services/api";

const TRUST_LEVELS = [
  { level: 0, name: "L0 隔离", desc: "完全锁定，仅允许只读访问", color: "text-rose-deep" },
  { level: 1, name: "L1 基础", desc: "允许只读工具，可联网搜索", color: "text-amber-glow" },
  { level: 2, name: "L2 标准", desc: "允许文件读写，有限制", color: "text-biolum-300" },
  { level: 3, name: "L3 信任", desc: "允许代码执行", color: "text-biolum-200" },
  { level: 4, name: "L4 高度信任", desc: "允许终端命令", color: "text-biolum-100" },
  { level: 5, name: "L5 完全信任", desc: "无限制访问", color: "text-biolum-50" },
];

export default function SecuritySettings() {
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
          <div key={i} className="glass rounded-2xl p-6 animate-pulse">
            <div className="h-6 w-40 bg-biolum-500/10 rounded mb-4" />
            <div className="h-4 w-full bg-biolum-500/10 rounded mb-2" />
            <div className="h-4 w-3/4 bg-biolum-500/10 rounded" />
          </div>
        ))}
      </div>
    );
  }

  const security = settings.security || {};
  const sandbox = security.sandbox || {};
  const codeExec = security.code_execution || {};

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-5"
    >
      {/* 安全状态概览 */}
      <SettingCard
        title="安全状态"
        description="当前安全系统的运行状态"
        icon={<Shield className="w-4 h-4 text-biolum-300" />}
      >
        <div className="grid grid-cols-3 gap-3">
          <StatusBadge
            label="信任等级"
            value={`L${security.trust_level ?? 1}`}
            icon={<Lock className="w-3.5 h-3.5" />}
            ok
          />
          <StatusBadge
            label="沙箱"
            value={sandbox.enabled ? "运行中" : "已关闭"}
            icon={<Box className="w-3.5 h-3.5" />}
            ok={sandbox.enabled}
          />
          <StatusBadge
            label="自我保护"
            value={"启用"}
            icon={<ShieldCheck className="w-3.5 h-3.5" />}
            ok
          />
        </div>
      </SettingCard>

      {/* 信任等级 */}
      <SettingCard
        title="信任等级"
        description="控制 Agent 可执行的操作范围"
        icon={<ShieldAlert className="w-4 h-4 text-amber-glow" />}
      >
        <div className="space-y-2">
          {TRUST_LEVELS.map((tl) => {
            const isActive = (security.trust_level ?? 1) === tl.level;
            return (
              <div
                key={tl.level}
                className={`p-3 rounded-xl border transition cursor-pointer ${
                  isActive
                    ? "bg-biolum-500/10 border-biolum-500/30"
                    : "bg-abyss-900/30 border-biolum-500/10 hover:border-biolum-500/20"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-sm font-medium ${tl.color}`}>
                      {tl.name}
                    </span>
                    <span className="text-xs text-biolum-300/50">
                      {tl.desc}
                    </span>
                  </div>
                  {isActive && (
                    <CheckCircle2 className="w-4 h-4 text-biolum-400" />
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-4 pt-4 border-t border-biolum-500/10">
          <SettingRow
            label="自动升级阈值"
            description="连续成功多少次后自动升级"
          >
            <div className="w-40">
              <Slider
                value={security.promotion_threshold ?? 5}
                min={1}
                max={20}
                step={1}
                onChange={() => {}}
                unit=" 次"
              />
            </div>
          </SettingRow>
          <SettingRow
            label="自动降级阈值"
            description="连续失败多少次后自动降级"
          >
            <div className="w-40">
              <Slider
                value={security.demotion_threshold ?? 2}
                min={1}
                max={10}
                step={1}
                onChange={() => {}}
                unit=" 次"
              />
            </div>
          </SettingRow>
        </div>
      </SettingCard>

      {/* 沙箱配置 */}
      <SettingCard
        title="沙箱配置"
        description="代码执行的隔离环境"
        icon={<Box className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="启用沙箱"
          description="所有代码执行在隔离环境中运行"
        >
          <Toggle checked={sandbox.enabled ?? true} onChange={() => {}} />
        </SettingRow>
        <SettingRow
          label="执行超时"
          description="单次执行的最长时间"
        >
          <div className="w-40">
            <Slider
              value={sandbox.timeout_seconds ?? 30}
              min={5}
              max={300}
              step={5}
              onChange={() => {}}
              unit=" 秒"
            />
          </div>
        </SettingRow>
        <SettingRow
          label="最大内存"
          description="沙箱可使用的最大内存"
        >
          <div className="w-40">
            <Slider
              value={sandbox.max_memory_mb ?? 512}
              min={64}
              max={4096}
              step={64}
              onChange={() => {}}
              unit=" MB"
            />
          </div>
        </SettingRow>
      </SettingCard>

      {/* 代码执行限制 */}
      <SettingCard
        title="代码执行限制"
        description="禁止在代码执行中导入的模块"
        icon={<ShieldX className="w-4 h-4 text-rose-deep" />}
      >
        <div className="flex flex-wrap gap-2">
          {(codeExec.blocked_modules || []).map((mod: string) => (
            <span
              key={mod}
              className="px-2.5 py-1 rounded-lg text-xs bg-rose-deep/10 text-rose-deep/80 border border-rose-deep/20 font-mono"
            >
              {mod}
            </span>
          ))}
          {(codeExec.blocked_modules || []).length === 0 && (
            <span className="text-xs text-biolum-300/40">无限制模块</span>
          )}
        </div>
      </SettingCard>

      {/* 自我保护 */}
      <SettingCard
        title="自我保护"
        description="Agent 的核心代码完整性保护"
        icon={<ShieldCheck className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="完整性校验"
          description="定期校验核心文件是否被篡改"
        >
          <Toggle checked={true} onChange={() => {}} />
        </SettingRow>
        <SettingRow
          label="自动备份"
          description="检测到变更时自动备份核心文件"
        >
          <Toggle checked={true} onChange={() => {}} />
        </SettingRow>
        <BackupList />
      </SettingCard>

      {/* 审计日志 */}
      <SettingCard
        title="审计日志"
        description="所有敏感操作的记录"
        icon={<Clock className="w-4 h-4 text-biolum-300" />}
      >
        <SettingRow
          label="日志路径"
          description="审计日志文件位置"
        >
          <code className="text-[10px] font-mono text-biolum-300/60 bg-abyss-900/50 px-2 py-1 rounded">
            {security.audit_log?.log_path || "./castorice_data/audit.log"}
          </code>
        </SettingRow>
      </SettingCard>
    </motion.div>
  );
}

function StatusBadge({
  label,
  value,
  icon,
  ok = true,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  ok?: boolean;
}) {
  return (
    <div className="p-3 rounded-xl bg-abyss-900/40 border border-biolum-500/10">
      <div className="flex items-center gap-1.5 mb-1">
        <span className={ok ? "text-biolum-400" : "text-rose-deep/70"}>
          {icon}
        </span>
        <span className="text-[11px] text-biolum-300/50">{label}</span>
      </div>
      <div
        className={`text-sm font-medium ${
          ok ? "text-biolum-100" : "text-rose-deep/80"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function BackupList() {
  const [backups, setBackups] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        setBackups([
          "backup_20260724_061711_manual_test",
          "backup_20260723_182234_auto",
          "backup_20260722_114509_initial",
        ]);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading) {
    return <div className="h-8 animate-pulse bg-biolum-500/10 rounded" />;
  }

  return (
    <div className="mt-3 pt-3 border-t border-biolum-500/10">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-biolum-300/60">备份列表</span>
        <div className="flex gap-1">
          <button className="p-1.5 rounded-lg bg-biolum-500/10 text-biolum-300 hover:bg-biolum-500/20 transition">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button className="p-1.5 rounded-lg bg-biolum-500/10 text-biolum-300 hover:bg-biolum-500/20 transition">
            <Save className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div className="space-y-1.5 max-h-40 overflow-y-auto">
        {backups.map((b) => (
          <div
            key={b}
            className="flex items-center justify-between p-2 rounded-lg bg-abyss-900/40 border border-biolum-500/10"
          >
            <code className="text-[10px] font-mono text-biolum-200/70">
              {b}
            </code>
            <div className="flex gap-1">
              <button className="p-1 rounded text-biolum-300/50 hover:text-biolum-300 transition">
                <RefreshCw className="w-3 h-3" />
              </button>
              <button className="p-1 rounded text-rose-deep/50 hover:text-rose-deep transition">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
