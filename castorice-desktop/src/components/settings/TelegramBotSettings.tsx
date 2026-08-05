import { useState, useEffect } from "react";
import { Send, Power, PowerOff, AlertCircle, CheckCircle2, Settings as SettingsIcon, ShieldCheck } from "lucide-react";
import SettingCard from "./SettingCard";
import api from "@/services/api";

export default function TelegramBotSettings() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" | "info" } | null>(null);

  const loadStatus = async () => {
    setLoading(true);
    try {
      const res = await api.telegramStatus();
      if (res?.success) setStatus(res);
    } catch (e) {}
    finally { setLoading(false); }
  };

  useEffect(() => { loadStatus(); }, []);

  const showMsg = (text: string, type: "success" | "error" | "info" = "info") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 4000);
  };

  const handleStart = async () => {
    setActionLoading(true);
    try {
      const res = await api.telegramStart();
      showMsg(res?.success ? "Telegram Bot 启动成功" : res?.message || "启动失败", res?.success ? "success" : "error");
    } catch (e) { showMsg("请求失败", "error"); }
    finally { setActionLoading(false); setTimeout(loadStatus, 800); }
  };

  const handleStop = async () => {
    setActionLoading(true);
    try {
      const res = await api.telegramStop();
      showMsg(res?.success ? "已停止" : res?.message || "停止失败", res?.success ? "success" : "error");
    } catch (e) { showMsg("请求失败", "error"); }
    finally { setActionLoading(false); setTimeout(loadStatus, 500); }
  };

  return (
    <div className="space-y-5">
      <SettingCard
        title="Telegram Bot"
        description="通过 Telegram Bot API 接入，让 Castorice 在 Telegram 私聊和群组中与用户互动"
        icon={<Send className="w-5 h-5 text-biolum-300" />}
      >
        <div className={`rounded-xl p-4 flex items-center justify-between ${
          status?.running ? "bg-emerald-glow/10 border border-emerald-glow/20"
            : status?.configured ? "bg-amber-glow/10 border border-amber-glow/20"
            : "bg-biolum-500/5 border border-biolum-500/10"
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
              status?.running ? "bg-emerald-glow/20"
                : status?.configured ? "bg-amber-glow/20"
                : "bg-biolum-500/10"
            }`}>
              {status?.running
                ? <CheckCircle2 className="w-5 h-5 text-emerald-glow" />
                : <AlertCircle className={`w-5 h-5 ${status?.configured ? "text-amber-glow" : "text-biolum-300/40"}`} />}
            </div>
            <div>
              <div className="text-sm font-medium text-biolum-100">
                {status?.running ? "运行中" : status?.configured ? "已配置，未启动" : "未配置"}
              </div>
              <div className="text-[11px] text-biolum-300/50">
                {loading ? "加载中..." :
                  status?.info?.username ? `@${status.info.username}` :
                  status?.running ? "正在接收消息" :
                  status?.configured ? "点击启动" :
                  "请在配置文件中设置 telegram.bot_token"}
              </div>
            </div>
          </div>
          {status?.running ? (
            <button onClick={handleStop} disabled={actionLoading}
              className="px-4 py-2 rounded-lg bg-rose-deep/20 text-rose-deep text-xs font-medium hover:bg-rose-deep/30 transition-all flex items-center gap-2 disabled:opacity-60">
              <PowerOff className="w-3.5 h-3.5" /> 停止
            </button>
          ) : (
            <button onClick={handleStart} disabled={actionLoading || !status?.configured}
              className="px-4 py-2 rounded-lg bg-gradient-to-r from-biolum-400 to-biolum-600 text-abyss-950 text-xs font-medium hover:brightness-110 transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">
              <Power className="w-3.5 h-3.5" /> 启动
            </button>
          )}
        </div>
        {message && (
          <div className={`text-xs px-3 py-2 rounded-lg flex items-center gap-2 mt-3 ${
            message.type === "success" ? "bg-emerald-glow/10 text-emerald-glow"
              : message.type === "error" ? "bg-rose-deep/10 text-rose-deep"
              : "bg-biolum-500/10 text-biolum-300"
          }`}>
            {message.type === "success" && <CheckCircle2 className="w-3.5 h-3.5" />}
            {message.type === "error" && <AlertCircle className="w-3.5 h-3.5" />}
            {message.text}
          </div>
        )}
      </SettingCard>

      {status && (
        <SettingCard
          title="当前配置"
          description="在 castorice_config.yaml 或 .env 中配置 telegram.bot_token"
          icon={<SettingsIcon className="w-5 h-5 text-biolum-300" />}
        >
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-abyss-800/40 rounded-xl p-3 col-span-2">
              <div className="text-[10px] text-biolum-300/40 mb-1">Bot Token</div>
              <div className="text-xs font-mono text-biolum-200 truncate">
                {status.configured ? "•••••••••• (已配置)" : "未配置"}
              </div>
            </div>
          </div>
          <div className="mt-3 text-[10px] text-biolum-300/30">
            在 @BotFather 创建 Bot，获取 token 后填入配置。支持私聊和白名单群组。
          </div>
        </SettingCard>
      )}
    </div>
  );
}
