import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Cpu, Check, X, Save } from "lucide-react";
import api from "@/services/api";

interface Provider {
  id: string;
  name: string;
  models: string[];
  hasKey: boolean;
}

export default function LLMConfig() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeProvider, setActiveProvider] = useState("openai");
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);

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

  const mockProviders: Provider[] = [
    {
      id: "openai",
      name: "OpenAI",
      models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
      hasKey: true,
    },
    {
      id: "anthropic",
      name: "Anthropic Claude",
      models: ["claude-3-5-sonnet-20241022", "claude-3-opus", "claude-3-haiku"],
      hasKey: true,
    },
    {
      id: "ollama",
      name: "Ollama (本地)",
      models: ["llama3.1:8b", "qwen2.5:7b", "gemma2:9b"],
      hasKey: true,
    },
    {
      id: "gemini",
      name: "Google Gemini",
      models: ["gemini-1.5-flash", "gemini-1.5-pro"],
      hasKey: false,
    },
    {
      id: "qwen",
      name: "通义千问",
      models: ["qwen-plus", "qwen-max", "qwen-turbo"],
      hasKey: false,
    },
  ];

  return (
    <div className="space-y-6">
      {/* 供应商选择 */}
      <div className="glass rounded-2xl p-6">
        <h2 className="font-display text-xl text-biolum-100 mb-5">模型供应商</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {mockProviders.map((provider) => (
            <motion.button
              key={provider.id}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              onClick={() => setActiveProvider(provider.id)}
              className={`relative text-left p-4 rounded-xl border transition-all ${
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
              <div className="flex items-center gap-2 mb-1">
                <Cpu className={`w-4 h-4 ${activeProvider === provider.id ? "text-biolum-300" : "text-biolum-300/40"}`} />
                <span className="text-sm font-medium text-biolum-100">{provider.name}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-2">
                {provider.hasKey ? (
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
            </motion.button>
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
