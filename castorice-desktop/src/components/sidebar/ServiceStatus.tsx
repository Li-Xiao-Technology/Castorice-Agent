import { motion, AnimatePresence } from "framer-motion";
import { Cpu, Circle, Zap, MessageCircle, Brain, Radio } from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import type { AutonomousAction } from "@/types";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

function ActionIcon({ mode }: { mode: string }) {
  if (mode === "deep") return <Brain className="w-3 h-3 text-violet-glow" />;
  return <Zap className="w-3 h-3 text-amber-glow" />;
}

function AutonomousActivity({ actions, running }: { actions: AutonomousAction[]; running: boolean }) {
  if (!running || !actions || actions.length === 0) {
    return (
      <div className="text-[10px] text-biolum-300/30 text-center py-1">
        暂无自主活动记录
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {actions.slice(0, 3).map((action, idx) => (
        <motion.div
          key={`${action.time}-${idx}`}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: idx * 0.05 }}
          className="flex items-start gap-2 text-[10px]"
        >
          <div className="mt-0.5 shrink-0">
            <ActionIcon mode={action.mode} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-biolum-200/80 leading-tight line-clamp-2">
              {action.summary}
            </div>
            <div className="text-biolum-300/30 mt-0.5">
              {formatDistanceToNow(action.time * 1000, { addSuffix: true, locale: zhCN })}
              {action.duration_seconds > 0 && ` · ${action.duration_seconds}s`}
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}

export default function ServiceStatus() {
  const backendStatus = useAppStore((s) => s.backendStatus);
  const agentStatus = useAppStore((s) => s.agentStatus);

  const statusConfig = {
    idle: { label: "等待中", color: "text-biolum-300/40", dot: "bg-biolum-300/30" },
    starting: { label: "启动中", color: "text-amber-glow", dot: "bg-amber-glow" },
    running: { label: "运行中", color: "text-biolum-300", dot: "bg-biolum-400" },
    stopped: { label: "未连接", color: "text-rose-deep/70", dot: "bg-rose-deep/60" },
    error: { label: "异常", color: "text-rose-deep", dot: "bg-rose-deep" },
  }[backendStatus];

  return (
    <div className="glass rounded-xl p-3 space-y-3">
      <div className="flex items-center gap-3">
        <div className="relative">
          <Cpu
            className={`w-5 h-5 ${statusConfig.color}`}
            strokeWidth={1.8}
          />
          {backendStatus === "running" && (
            <motion.div
              animate={{ scale: [1, 1.6, 1], opacity: [0.6, 0, 0.6] }}
              transition={{ duration: 2, repeat: Infinity }}
              className="absolute inset-0 rounded-full bg-biolum-400/30"
            />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Circle className={`w-2 h-2 fill-current ${statusConfig.dot}`} />
            <span className={`text-xs font-medium ${statusConfig.color}`}>
              {statusConfig.label}
            </span>
          </div>
          {agentStatus && (
            <div className="text-[10px] text-biolum-300/40 mt-0.5 truncate">
              {agentStatus.provider} · {agentStatus.model}
            </div>
          )}
        </div>
      </div>

      {agentStatus && (
        <div className="grid grid-cols-3 gap-2 pt-3 border-t border-biolum-500/10">
          <div className="text-center">
            <div className="text-sm font-semibold text-biolum-200">
              {agentStatus.sessions_count}
            </div>
            <div className="text-[9px] text-biolum-300/40 tracking-wide">
              会话
            </div>
          </div>
          <div className="text-center border-x border-biolum-500/10">
            <div className="text-sm font-semibold text-biolum-200">
              {agentStatus.tools_count}
            </div>
            <div className="text-[9px] text-biolum-300/40 tracking-wide">
              工具
            </div>
          </div>
          <div className="text-center">
            <div className="text-sm font-semibold text-biolum-200">
              {agentStatus.skills_count}
            </div>
            <div className="text-[9px] text-biolum-300/40 tracking-wide">
              技能
            </div>
          </div>
        </div>
      )}

      <AnimatePresence>
        {agentStatus && (agentStatus.eigenflux_available || agentStatus.autonomous_running) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="pt-3 border-t border-biolum-500/10 space-y-3"
          >
            {agentStatus.eigenflux_available && (
              <div className="flex items-center gap-2 text-[10px]">
                <Radio className="w-3 h-3 text-emerald-glow" />
                <span className="text-biolum-300/60">EigenFlux</span>
                <Circle className={`w-1.5 h-1.5 ml-auto ${agentStatus.eigenflux_authenticated ? "fill-emerald-glow text-emerald-glow" : "fill-amber-glow text-amber-glow"}`} />
                <span className={agentStatus.eigenflux_authenticated ? "text-emerald-glow" : "text-amber-glow"}>
                  {agentStatus.eigenflux_authenticated ? "已连接" : "待验证"}
                </span>
              </div>
            )}

            {agentStatus.autonomous_running && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-[10px]">
                  <MessageCircle className="w-3 h-3 text-violet-glow" />
                  <span className="text-biolum-300/60">自主决策</span>
                  <span className="ml-auto text-violet-glow font-medium">
                    {agentStatus.autonomous_total_decisions} 次
                  </span>
                </div>
                <AutonomousActivity
                  actions={agentStatus.autonomous_recent || []}
                  running={agentStatus.autonomous_running}
                />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
