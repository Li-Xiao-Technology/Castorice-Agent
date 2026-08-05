import { useState, useEffect } from "react";
import {
  Plug,
  Power,
  PowerOff,
  AlertCircle,
  CheckCircle2,
  Settings as SettingsIcon,
  Plus,
  Trash2,
  Server,
  Wrench,
  ChevronDown,
  ChevronUp,
  Play,
  Square,
} from "lucide-react";
import SettingCard from "./SettingCard";
import api from "@/services/api";

interface MCPServer {
  name: string;
  running: boolean;
  tool_count: number;
  config: {
    name: string;
    command: string;
    args: string[];
    env: Record<string, string>;
    cwd?: string;
  };
}

interface MCPTool {
  name: string;
  description?: string;
  mcp_server: string;
  inputSchema?: Record<string, any>;
}

export default function MCPSettings() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" | "info" } | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [newServer, setNewServer] = useState({
    name: "",
    command: "",
    args: "",
    env: "",
    cwd: "",
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const [sRes, tRes] = await Promise.all([
        api.mcpListServers(),
        api.mcpTools(),
      ]);
      if (sRes?.success) setServers(sRes.servers || []);
      if (tRes?.success) setTools(tRes.tools || []);
    } catch (e) {
      // API 可能不存在
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const showMsg = (text: string, type: "success" | "error" | "info" = "info") => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 4000);
  };

  const handleStartAll = async () => {
    setActionLoading(true);
    try {
      const res = await api.mcpStartAll();
      if (res?.success) {
        showMsg("所有 MCP 服务器正在启动", "success");
      } else {
        showMsg(res?.message || "启动失败", "error");
      }
    } catch (e) {
      showMsg("请求失败", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadData, 1500);
    }
  };

  const handleStopAll = async () => {
    setActionLoading(true);
    try {
      const res = await api.mcpStopAll();
      if (res?.success) {
        showMsg("所有 MCP 服务器已停止", "success");
      } else {
        showMsg(res?.message || "停止失败", "error");
      }
    } catch (e) {
      showMsg("请求失败", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadData, 800);
    }
  };

  const handleAddServer = async () => {
    if (!newServer.name.trim() || !newServer.command.trim()) {
      showMsg("请填写服务器名称和命令", "error");
      return;
    }
    setActionLoading(true);
    try {
      const payload: Record<string, any> = {
        name: newServer.name.trim(),
        command: newServer.command.trim(),
      };
      if (newServer.args.trim()) {
        payload.args = newServer.args.split(/\s+/).filter(Boolean);
      }
      if (newServer.env.trim()) {
        const env: Record<string, string> = {};
        newServer.env.split(/[,;]/).forEach((pair) => {
          const [k, v] = pair.split("=");
          if (k && v) env[k.trim()] = v.trim();
        });
        if (Object.keys(env).length) payload.env = env;
      }
      if (newServer.cwd.trim()) {
        payload.cwd = newServer.cwd.trim();
      }
      const res = await api.mcpAddServer(payload);
      if (res?.success) {
        showMsg(`已添加 MCP 服务器: ${newServer.name}`, "success");
        setNewServer({ name: "", command: "", args: "", env: "", cwd: "" });
        setShowAddForm(false);
      } else {
        showMsg(res?.message || "添加失败", "error");
      }
    } catch (e) {
      showMsg("请求失败", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadData, 500);
    }
  };

  const handleRemoveServer = async (name: string) => {
    if (!confirm(`确定要移除 MCP 服务器 "${name}" 吗？`)) return;
    setActionLoading(true);
    try {
      const res = await api.mcpRemoveServer(name);
      if (res?.success) {
        showMsg(`已移除: ${name}`, "success");
      } else {
        showMsg(res?.message || "移除失败", "error");
      }
    } catch (e) {
      showMsg("请求失败", "error");
    } finally {
      setActionLoading(false);
      setTimeout(loadData, 500);
    }
  };

  const runningCount = servers.filter((s) => s.running).length;
  const totalTools = tools.length;

  return (
    <div className="space-y-5">
      <SettingCard
        title="MCP 客户端"
        description="通过 Model Context Protocol 连接外部工具服务器，扩展 Castorice 的能力"
        icon={<Plug className="w-5 h-5 text-biolum-300" />}
      >
        <div
          className={`rounded-xl p-4 flex items-center justify-between ${
            runningCount > 0
              ? "bg-emerald-glow/10 border border-emerald-glow/20"
              : servers.length > 0
              ? "bg-amber-glow/10 border border-amber-glow/20"
              : "bg-biolum-500/5 border border-biolum-500/10"
          }`}
        >
          <div className="flex items-center gap-3">
            <div
              className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                runningCount > 0
                  ? "bg-emerald-glow/20"
                  : servers.length > 0
                  ? "bg-amber-glow/20"
                  : "bg-biolum-500/10"
              }`}
            >
              {runningCount > 0 ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-glow" />
              ) : (
                <AlertCircle
                  className={`w-5 h-5 ${
                    servers.length > 0 ? "text-amber-glow" : "text-biolum-300/40"
                  }`}
                />
              )}
            </div>
            <div>
              <div className="text-sm font-medium text-biolum-100">
                {runningCount > 0
                  ? `${runningCount} 个服务器运行中`
                  : servers.length > 0
                  ? `${servers.length} 个服务器已配置`
                  : "尚未配置 MCP 服务器"}
              </div>
              <div className="text-[11px] text-biolum-300/50">
                {loading
                  ? "加载中..."
                  : totalTools > 0
                  ? `已发现 ${totalTools} 个工具`
                  : "添加 MCP 服务器以发现更多工具"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {runningCount > 0 ? (
              <button
                onClick={handleStopAll}
                disabled={actionLoading}
                className="px-4 py-2 rounded-lg bg-rose-deep/20 text-rose-deep text-xs font-medium hover:bg-rose-deep/30 transition-all flex items-center gap-2 disabled:opacity-60"
              >
                <Square className="w-3.5 h-3.5" /> 全部停止
              </button>
            ) : (
              <button
                onClick={handleStartAll}
                disabled={actionLoading || servers.length === 0}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-biolum-400 to-biolum-600 text-abyss-950 text-xs font-medium hover:brightness-110 transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Play className="w-3.5 h-3.5" /> 全部启动
              </button>
            )}
          </div>
        </div>

        {message && (
          <div
            className={`text-xs px-3 py-2 rounded-lg flex items-center gap-2 mt-3 ${
              message.type === "success"
                ? "bg-emerald-glow/10 text-emerald-glow"
                : message.type === "error"
                ? "bg-rose-deep/10 text-rose-deep"
                : "bg-biolum-500/10 text-biolum-300"
            }`}
          >
            {message.type === "success" && <CheckCircle2 className="w-3.5 h-3.5" />}
            {message.type === "error" && <AlertCircle className="w-3.5 h-3.5" />}
            {message.text}
          </div>
        )}
      </SettingCard>

      {/* 服务器列表 */}
      <SettingCard
        title="服务器列表"
        description={`已配置 ${servers.length} 个 MCP 服务器`}
        icon={<Server className="w-5 h-5 text-biolum-300" />}
      >
        {servers.length === 0 ? (
          <div className="text-center py-8 text-biolum-300/40 text-sm">
            暂无 MCP 服务器，点击下方按钮添加
          </div>
        ) : (
          <div className="space-y-3">
            {servers.map((server) => (
              <div
                key={server.name}
                className="bg-abyss-800/40 rounded-xl p-3 border border-biolum-500/10"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        server.running ? "bg-emerald-glow/20" : "bg-biolum-500/10"
                      }`}
                    >
                      <Server
                        className={`w-4 h-4 ${
                          server.running ? "text-emerald-glow" : "text-biolum-300/40"
                        }`}
                      />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-biolum-100">{server.name}</div>
                      <div className="text-[10px] text-biolum-300/40 font-mono">
                        {server.config.command}{" "}
                        {server.config.args?.join(" ")}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded ${
                        server.running
                          ? "bg-emerald-glow/15 text-emerald-glow"
                          : "bg-biolum-500/10 text-biolum-300/50"
                      }`}
                    >
                      {server.running ? "运行中" : "已停止"}
                    </span>
                    <span className="text-[10px] text-biolum-300/30">
                      {server.tool_count} 工具
                    </span>
                    <button
                      onClick={() => handleRemoveServer(server.name)}
                      disabled={actionLoading}
                      className="p-1.5 rounded-lg text-rose-deep/60 hover:text-rose-deep hover:bg-rose-deep/10 transition-all disabled:opacity-40"
                      title="移除服务器"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 添加服务器表单 */}
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="mt-4 w-full py-2.5 rounded-xl border border-dashed border-biolum-500/20 text-biolum-300/60 hover:text-biolum-200 hover:border-biolum-500/40 hover:bg-biolum-500/5 transition-all flex items-center justify-center gap-2 text-sm"
        >
          {showAddForm ? (
            <>
              <ChevronUp className="w-4 h-4" /> 取消添加
            </>
          ) : (
            <>
              <Plus className="w-4 h-4" /> 添加 MCP 服务器
            </>
          )}
        </button>

        {showAddForm && (
          <div className="mt-4 bg-abyss-800/40 rounded-xl p-4 border border-biolum-500/10 space-y-3">
            <div>
              <label className="text-[10px] text-biolum-300/40 mb-1 block">服务器名称 *</label>
              <input
                type="text"
                value={newServer.name}
                onChange={(e) => setNewServer({ ...newServer, name: e.target.value })}
                placeholder="例如：filesystem"
                className="w-full px-3 py-2 rounded-lg bg-abyss-900/60 border border-biolum-500/15 text-sm text-biolum-100 placeholder-biolum-300/20 focus:outline-none focus:border-biolum-500/40"
              />
            </div>
            <div>
              <label className="text-[10px] text-biolum-300/40 mb-1 block">命令 *</label>
              <input
                type="text"
                value={newServer.command}
                onChange={(e) => setNewServer({ ...newServer, command: e.target.value })}
                placeholder="例如：python"
                className="w-full px-3 py-2 rounded-lg bg-abyss-900/60 border border-biolum-500/15 text-sm text-biolum-100 placeholder-biolum-300/20 focus:outline-none focus:border-biolum-500/40"
              />
            </div>
            <div>
              <label className="text-[10px] text-biolum-300/40 mb-1 block">参数（空格分隔）</label>
              <input
                type="text"
                value={newServer.args}
                onChange={(e) => setNewServer({ ...newServer, args: e.target.value })}
                placeholder="例如：-m mcp_server_filesystem"
                className="w-full px-3 py-2 rounded-lg bg-abyss-900/60 border border-biolum-500/15 text-sm text-biolum-100 placeholder-biolum-300/20 focus:outline-none focus:border-biolum-500/40"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-biolum-300/40 mb-1 block">环境变量（KEY=VAL, 逗号分隔）</label>
                <input
                  type="text"
                  value={newServer.env}
                  onChange={(e) => setNewServer({ ...newServer, env: e.target.value })}
                  placeholder="例如：API_KEY=xxx,DEBUG=1"
                  className="w-full px-3 py-2 rounded-lg bg-abyss-900/60 border border-biolum-500/15 text-sm text-biolum-100 placeholder-biolum-300/20 focus:outline-none focus:border-biolum-500/40"
                />
              </div>
              <div>
                <label className="text-[10px] text-biolum-300/40 mb-1 block">工作目录</label>
                <input
                  type="text"
                  value={newServer.cwd}
                  onChange={(e) => setNewServer({ ...newServer, cwd: e.target.value })}
                  placeholder="可选"
                  className="w-full px-3 py-2 rounded-lg bg-abyss-900/60 border border-biolum-500/15 text-sm text-biolum-100 placeholder-biolum-300/20 focus:outline-none focus:border-biolum-500/40"
                />
              </div>
            </div>
            <button
              onClick={handleAddServer}
              disabled={actionLoading}
              className="w-full py-2 rounded-lg bg-gradient-to-r from-biolum-400 to-biolum-600 text-abyss-950 text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" /> 添加服务器
            </button>
          </div>
        )}
      </SettingCard>

      {/* 工具列表 */}
      {tools.length > 0 && (
        <SettingCard
          title="已发现的工具"
          description={`来自 ${new Set(tools.map((t) => t.mcp_server)).size} 个服务器的 ${tools.length} 个工具`}
          icon={<Wrench className="w-5 h-5 text-biolum-300" />}
        >
          <button
            onClick={() => setShowTools(!showTools)}
            className="w-full flex items-center justify-between text-sm text-biolum-200 hover:text-biolum-100"
          >
            <span>展开查看 {tools.length} 个工具</span>
            {showTools ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          {showTools && (
            <div className="mt-3 space-y-2 max-h-80 overflow-y-auto">
              {tools.map((tool, idx) => (
                <div
                  key={`${tool.mcp_server}-${tool.name}-${idx}`}
                  className="bg-abyss-800/40 rounded-lg p-3 border border-biolum-500/10"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-mono text-biolum-100">{tool.name}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-glow/15 text-violet-glow">
                      {tool.mcp_server}
                    </span>
                  </div>
                  {tool.description && (
                    <div className="text-[11px] text-biolum-300/50">{tool.description}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </SettingCard>
      )}
    </div>
  );
}
