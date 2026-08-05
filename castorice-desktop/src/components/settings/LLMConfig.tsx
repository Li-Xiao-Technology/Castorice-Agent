import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Cpu, Check, X, Save, Plus, Trash2, Settings as SettingsIcon, ChevronDown } from "lucide-react";
import api from "@/services/api";

interface Provider {
  id: string;
  name: string;
  models: string[];
  has_key: boolean;
  is_custom: boolean;
  base_url?: string;
  model?: string;
}

export default function LLMConfig() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeProvider, setActiveProvider] = useState("openai");
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);

  // 添加自定义供应商的表单状态
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newBaseUrl, setNewBaseUrl] = useState("");
  const [newApiKey, setNewApiKey] = useState("");
  const [newModel, setNewModel] = useState("");
  const [addLoading, setAddLoading] = useState(false);

  // 编辑某个自定义供应商
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editBaseUrl, setEditBaseUrl] = useState("");
  const [editApiKey, setEditApiKey] = useState("");
  const [editModel, setEditModel] = useState("");
  const [editLoading, setEditLoading] = useState(false);

  const loadProviders = async () => {
    try {
      const res = await api.listProviders();
      if (res?.success && res.providers) {
        setProviders(res.providers);
      }
    } catch (e) {
      // 失败时使用空列表
    }
  };

  useEffect(() => {
    const load = async () => {
      try {
        const settings = await api.getSettings();
        if (settings?.llm) {
          setActiveProvider(settings.llm.provider || "openai");
          setTemperature(settings.llm.temperature || 0.7);
          setMaxTokens(settings.llm.max_tokens || 4096);
        }
      } catch (e) {
        // 静默失败
      } finally {
        setLoading(false);
      }
    };
    load();
    loadProviders();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      const res = await api.updateSettings({
        temperature,
        max_tokens: maxTokens,
        provider: activeProvider,
      });
      if (res?.success) {
        setSaveMsg("✓ 已保存，立即生效");
        setTimeout(() => setSaveMsg(""), 3000);
      } else {
        setSaveMsg("✗ 保存失败: " + (res?.message || "未知错误"));
      }
    } catch (e: any) {
      setSaveMsg("✗ 保存失败: " + (e?.message || String(e)));
    } finally {
      setSaving(false);
    }
  };

  const handleAddProvider = async () => {
    if (!newName.trim() || !newBaseUrl.trim()) return;
    setAddLoading(true);
    try {
      const res = await api.addProvider({
        name: newName.trim(),
        base_url: newBaseUrl.trim(),
        api_key: newApiKey,
        model: newModel.trim(),
      });
      if (res?.success) {
        setShowAddForm(false);
        setNewName("");
        setNewBaseUrl("");
        setNewApiKey("");
        setNewModel("");
        await loadProviders();
      } else {
        alert("添加失败: " + (res?.message || "未知错误"));
      }
    } catch (e: any) {
      alert("添加失败: " + (e?.message || String(e)));
    } finally {
      setAddLoading(false);
    }
  };

  const startEdit = (p: Provider) => {
    setEditingId(p.id);
    setEditName(p.name);
    setEditBaseUrl(p.base_url || "");
    setEditApiKey("");
    setEditModel(p.model || "");
  };

  const handleUpdateProvider = async () => {
    if (!editingId) return;
    setEditLoading(true);
    try {
      const payload: Record<string, any> = {};
      if (editName.trim()) payload.name = editName.trim();
      if (editBaseUrl.trim()) payload.base_url = editBaseUrl.trim();
      if (editApiKey) payload.api_key = editApiKey;
      if (editModel.trim()) payload.model = editModel.trim();
      const res = await api.updateProvider(editingId, payload);
      if (res?.success) {
        setEditingId(null);
        await loadProviders();
      } else {
        alert("更新失败: " + (res?.message || "未知错误"));
      }
    } catch (e: any) {
      alert("更新失败: " + (e?.message || String(e)));
    } finally {
      setEditLoading(false);
    }
  };

  const handleDeleteProvider = async (p: Provider) => {
    if (!confirm(`确定要删除自定义供应商「${p.name}」吗？`)) return;
    try {
      const res = await api.deleteProvider(p.id);
      if (res?.success) {
        if (activeProvider === p.id) {
          setActiveProvider("openai");
        }
        await loadProviders();
      } else {
        alert("删除失败: " + (res?.message || "未知错误"));
      }
    } catch (e: any) {
      alert("删除失败: " + (e?.message || String(e)));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-6 h-6 border-2 border-biolum-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 供应商选择 */}
      <div className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-display text-xl text-biolum-100">模型供应商</h2>
          <motion.button
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            onClick={() => setShowAddForm(!showAddForm)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-biolum-500/10 text-biolum-300 text-sm hover:bg-biolum-500/20 transition-colors"
          >
            <Plus className="w-4 h-4" />
            添加自定义 API
          </motion.button>
        </div>

        {/* 添加自定义供应商表单 */}
        <AnimatePresence>
          {showAddForm && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden mb-5"
            >
              <div className="p-4 rounded-xl bg-abyss-900/50 border border-biolum-500/20 space-y-3">
                <div className="text-sm text-biolum-200 font-medium">新增自定义供应商（OpenAI 兼容协议）</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <input
                    type="text"
                    placeholder="供应商名称（例如：我的 API）"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="text"
                    placeholder="Base URL（例如：https://api.example.com/v1）"
                    value={newBaseUrl}
                    onChange={(e) => setNewBaseUrl(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="password"
                    placeholder="API Key（可选）"
                    value={newApiKey}
                    onChange={(e) => setNewApiKey(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="text"
                    placeholder="默认模型名（可选）"
                    value={newModel}
                    onChange={(e) => setNewModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 pt-1">
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setShowAddForm(false)}
                    className="px-4 py-2 rounded-lg text-sm text-biolum-300/60 hover:text-biolum-300 transition-colors"
                  >
                    取消
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={handleAddProvider}
                    disabled={addLoading || !newName.trim() || !newBaseUrl.trim()}
                    className="px-4 py-2 rounded-lg bg-biolum-500 text-abyss-950 text-sm font-medium hover:bg-biolum-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {addLoading ? "添加中..." : "添加"}
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 供应商列表 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {providers.map((provider) => (
            <div key={provider.id}>
              {editingId === provider.id ? (
                // 编辑模式
                <div className="p-4 rounded-xl bg-abyss-900/50 border border-biolum-500/30 space-y-3">
                  <input
                    type="text"
                    placeholder="名称"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="text"
                    placeholder="Base URL"
                    value={editBaseUrl}
                    onChange={(e) => setEditBaseUrl(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="password"
                    placeholder="新 API Key（留空则不修改）"
                    value={editApiKey}
                    onChange={(e) => setEditApiKey(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <input
                    type="text"
                    placeholder="默认模型名"
                    value={editModel}
                    onChange={(e) => setEditModel(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-abyss-950 border border-biolum-500/20 text-biolum-100 text-sm focus:outline-none focus:border-biolum-500/50"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1.5 rounded-lg text-sm text-biolum-300/60 hover:text-biolum-300 transition-colors"
                    >
                      取消
                    </motion.button>
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={handleUpdateProvider}
                      disabled={editLoading}
                      className="px-3 py-1.5 rounded-lg bg-biolum-500 text-abyss-950 text-sm font-medium hover:bg-biolum-400 transition-colors disabled:opacity-50"
                    >
                      {editLoading ? "保存中..." : "保存"}
                    </motion.button>
                  </div>
                </div>
              ) : (
                // 显示模式
                <motion.button
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.99 }}
                  onClick={() => setActiveProvider(provider.id)}
                  className={`relative w-full text-left p-4 rounded-xl border transition-all ${
                    activeProvider === provider.id
                      ? "bg-biolum-500/10 border-biolum-500/30"
                      : "bg-abyss-800/30 border-biolum-500/10 hover:border-biolum-500/20"
                  }`}
                >
                  {activeProvider === provider.id && (
                    <div className="absolute top-3 right-3 w-5 h-5 rounded-full bg-biolum-500 flex items-center justify-center">
                      <Check className="w-3 h-3 text-abyss-950" strokeWidth={3} />
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-1 pr-20">
                    <Cpu className={`w-4 h-4 ${activeProvider === provider.id ? "text-biolum-300" : "text-biolum-300/40"}`} />
                    <span className="text-sm font-medium text-biolum-100">{provider.name}</span>
                    {provider.is_custom && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-biolum-500/20 text-biolum-300">自定义</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-2">
                    {provider.has_key ? (
                      <>
                        <Check className="w-3 h-3 text-biolum-400" />
                        <span className="text-[10px] text-biolum-400">已配置 API Key</span>
                      </>
                    ) : (
                      <>
                        <X className="w-3 h-3 text-rose-deep/60" />
                        <span className="text-[10px] text-rose-deep/60">未配置 API Key</span>
                      </>
                    )}
                  </div>
                  {provider.is_custom && (
                    <div className="flex items-center gap-1 mt-3 pt-3 border-t border-biolum-500/10">
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={(e) => { e.stopPropagation(); startEdit(provider); }}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-biolum-300/70 hover:text-biolum-300 hover:bg-biolum-500/10 transition-colors"
                      >
                        <SettingsIcon className="w-3 h-3" />
                        编辑
                      </motion.button>
                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        onClick={(e) => { e.stopPropagation(); handleDeleteProvider(provider); }}
                        className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-rose-deep/70 hover:text-rose-deep hover:bg-rose-deep/10 transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                        删除
                      </motion.button>
                    </div>
                  )}
                </motion.button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 参数调整 */}
      <div className="glass rounded-2xl p-6">
        <h2 className="font-display text-xl text-biolum-100 mb-5">生成参数</h2>
        <div className="space-y-6">
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-biolum-200/80">Temperature (创造性)</label>
              <span className="text-sm font-mono text-biolum-300">{temperature.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0"
              max="2"
              step="0.05"
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-biolum-400"
            />
            <div className="flex justify-between mt-1 text-[10px] text-biolum-300/40">
              <span>精确</span>
              <span>平衡</span>
              <span>创意</span>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-biolum-200/80">Max Tokens (最大输出)</label>
              <span className="text-sm font-mono text-biolum-300">{maxTokens}</span>
            </div>
            <input
              type="range"
              min="256"
              max="8192"
              step="256"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value))}
              className="w-full accent-biolum-400"
            />
          </div>

          <div className="pt-4 border-t border-biolum-500/10">
            <div className="flex items-center gap-3">
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={handleSave}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-biolum-500 text-abyss-950 font-medium hover:bg-biolum-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Save className="w-4 h-4" />
                {saving ? "保存中..." : "保存设置"}
              </motion.button>
            </div>
            {saveMsg && (
              <p className={`mt-3 text-sm text-center ${saveMsg.startsWith("✓") ? "text-biolum-400" : "text-rose-deep"}`}>
                {saveMsg}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
