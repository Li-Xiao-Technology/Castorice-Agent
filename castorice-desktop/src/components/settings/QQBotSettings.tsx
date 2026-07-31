import { useState, useEffect } from "react";
import { MessageSquare, Power, PowerOff, AlertCircle, CheckCircle2, Settings as SettingsIcon, ShieldCheck, Users } from "lucide-react";
import SettingCard from "./SettingCard";
import api from "@/services/api";

interface QQStatus {
  running: boolean;
  configured: boolean;
  app_id: string;
  sandbox: boolean;
  intent: string;
  allowed_users: string[];
  allowed_groups: string[];
}

const intentLabels: Record<string, { label: string; desc: string }> = {
  basic: { label: "基础", desc: "频道@消息 + 频道私聊" },
  with_c2c: { label: "含C2C", desc: "基础 + 私聊消息" },
  all: { label: "全部", desc: "所有消息事件" },
};

export default function QQBotSettings() {
  const [status, setStatus] = useState<QQStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" | "info" } | null>(null);

  const loadStatus = async () => {
    setLoading(true);
    try {
      const res = await api.qqStatus();
      if (res?.success) {
        setStatus(res);
      }
    } catch (e) {
      // API 可能不存在于旧后端
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const showMsg = (text: string, type: "success" | "error" | "info" = "info") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 4000);
  };

  const handleStart = async () => {
    setActionLoading(true);
    try {
      const res = await api.qqStart();
      if (res?.success) {
        showMsg("QQ 机器人启动成功", "success");
      } else {
        showMsg(res?.message || "启动失败", "error");
      }
    } catch (e) {
      showMsg("请求失败，请检查后端服务", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadStatus, 800);
    }
  };

  const handleStop = async () => {
    setActionLoading(true);
    try {
      const res = await api.qqStop();
      if (res?.success) {
        showMsg("QQ 机器人已停止", "success");
      } else {
        showMsg(res?.message || "停止失败", "error");
      }
    } catch (e) {
      showMsg("请求失败，请检查后端服务", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadStatus, 500);
    }
  };

  const intentInfo = status?.intent ? intentLabels[status.intent] : null;

  return (
    <div className="space-y-5">
      <SettingCard
        title="QQ 机器人"
        description="通过 QQ 开放平台接入，让 Castorice 在 QQ 频道和群里与用户互动"
        icon={<MessageSquare className="w-5 h-5 text-biolum-300" />}
      >
        {/* 运行状态卡片 */}
        <div className={`rounded-xl p-4 flex items-center justify-between ${
          status?.running
            ? "bg-emerald-glow/10 border border-emerald-glow/20"
            : status?.configured
            ? "bg-amber-glow/10 border border-amber-glow/20"
            : "bg-biolum-500/5 border border-biolum-500/10"
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
              status?.running
                ? "bg-emerald-glow/20"
                : status?.configured
                ? "bg-amber-glow/20"
                : "bg-biolum-500/10"
            }`}>
              {status?.running ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-glow" />
              ) : (
                  <AlertCircle className={`w-5 h-5 ${status?.configured ? "text-amber-glow" : "text-biolum-300/40"}`} />
                )}
            </div>
            <div>
              <div className="text-sm font-medium text-biolum-100">
              {status?.running ? "运行中" : status?.configured ? "已配置，未启动" : "未配置"}
              </div>
              <div className="text-[11px] text-biolum-300/50">
                {loading ? "加载状态中..." :
                  status?.running ? "QQ 机器人正在接收消息" :
                  status?.configured ? "点击下方按钮启动机器人" :
                  "请先在 .env 中配置 QQ_BOT_APP_ID 和 QQ_BOT_APP_SECRET"
                }
              </div>
            </div>
          </div>
          {status?.running ? (
            <button
            onClick={handleStop}
            disabled={actionLoading}
            className="px-4 py-2 rounded-lg bg-rose-deep/20 text-rose-deep text-xs font-medium hover:bg-rose-deep/30 transition-all flex items-center gap-2 disabled:opacity-60"
          >
            <PowerOff className="w-3.5 h-3.5" />
            停止
          </button>
          ) : (
            <button
              onClick={handleStart}
              disabled={actionLoading || !status?.configured}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-biolum-400 to-biolum-600 text-abyss-950 text-xs font-medium hover:brightness-110 transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Power className="w-3.5 h-3.5" />
              启动
            </button>
          )}
        </div>

        {/* 消息提示 */}
        {message && (
          <div className={`text-xs px-3 py-2 rounded-lg flex items-center gap-2 ${
            message.type === "success" ? "bg-emerald-glow/10 text-emerald-glow" :
            message.type === "error" ? "bg-rose-deep/10 text-rose-deep" :
            "bg-biolum-500/10 text-biolum-300"
          }`}>
            {message.type === "success" && <CheckCircle2 className="w-3.5 h-3.5" />}
            {message.type === "error" && <AlertCircle className="w-3.5 h-3.5" />}
            {message.text}
          </div>
        )}
      </SettingCard>

      {/* 配置详情（只读展示） */}
      {status && (
        <SettingCard
          title="当前配置"
          description="在 .env 文件或 castorice_config.yaml 中修改以下配置项"
          icon={<SettingsIcon className="w-5 h-5 text-biolum-300" />}
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-abyss-800/40 rounded-xl p-3">
              <div className="text-[10px] text-biolum-300/40 mb-1">App ID</div>
              <div className="text-xs font-mono text-biolum-200 truncate">
                {status.app_id || "未配置"}
              </div>
            </div>
            <div className="bg-abyss-800/40 rounded-xl p-3">
              <div className="text-[10px] text-biolum-300/40 mb-1">运行环境</div>
              <div className="text-xs text-biolum-200">
                {status.sandbox ? "沙盒模式" : "正式环境"}
                <span className="text-[9px] text-biolum-300/30 ml-2">
                  ({status.sandbox ? "测试用" : "生产"})
                </span>
              </div>
            </div>
            <div className="bg-abyss-800/40 rounded-xl p-3">
              <div className="text-[10px] text-biolum-300/40 mb-1">消息订阅</div>
              <div className="text-xs text-biolum-200">
                {intentInfo?.label || status.intent || "未配置"}
                <span className="text-[9px] text-biolum-300/30 ml-2">
                  {intentInfo?.desc || ""}
                </span>
              </div>
            </div>
            <div className="bg-abyss-800/40 rounded-xl p-3 col-span-2">
              <div className="flex items-center gap-2 mb-2">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-glow" />
                <span className="text-[10px] text-biolum-300/40">白名单（安全保护）</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {status.allowed_users.length === 0 && status.allowed_groups.length === 0 ? (
                  <span className="text-[10px] text-amber-glow">
                    ⚠️ 白名单为空，启动时会被安全机制拒绝
                  </span>
                ) : (
                    <>
                      {status.allowed_users.map((u) => (
                        <span key={u} className="text-[10px] px-2 py-1 rounded bg-violet-glow/15 text-violet-glow">
                          用户: {u}
                        </span>
                      ))}
                      {status.allowed_groups.map((g) => (
                        <span key={g} className="text-[10px] px-2 py-1 rounded bg-blue-400/15 text-blue-400">
                          群: {g}
                        </span>
                      ))}
                    </>
                  )}
              </div>
            </div>
          </div>
        </SettingCard>
      )}
    </div>
  );
}
