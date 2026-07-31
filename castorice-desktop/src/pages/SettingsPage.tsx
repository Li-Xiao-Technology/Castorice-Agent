import { motion, AnimatePresence } from "framer-motion";
import { Settings as SettingsIcon, Cpu, Brain, Shield, Database, MessageSquare } from "lucide-react";
import { useState } from "react";
import LLMConfig from "@/components/settings/LLMConfig";
import AgentSettings from "@/components/settings/AgentSettings";
import MemorySettings from "@/components/settings/MemorySettings";
import SecuritySettings from "@/components/settings/SecuritySettings";
import QQBotSettings from "@/components/settings/QQBotSettings";

const sections = [
  { id: "llm", label: "模型设置", icon: Cpu },
  { id: "agent", label: "Agent 性格", icon: Brain },
  { id: "memory", label: "记忆设置", icon: Database },
  { id: "qq", label: "QQ 机器人", icon: MessageSquare },
  { id: "security", label: "安全保护", icon: Shield },
];

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState("llm");

  const renderContent = () => {
    switch (activeSection) {
      case "llm":
        return <LLMConfig />;
      case "agent":
        return <AgentSettings />;
      case "memory":
        return <MemorySettings />;
      case "qq":
        return <QQBotSettings />;
      case "security":
        return <SecuritySettings />;
      default:
        return null;
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-4xl mx-auto"
      >
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-biolum-400/20 to-biolum-600/20 border border-biolum-500/20 flex items-center justify-center">
              <SettingsIcon className="w-5 h-5 text-biolum-300" />
            </div>
            <h1 className="font-display text-3xl text-biolum-100 text-glow">设置</h1>
          </div>
          <p className="text-sm text-biolum-300/50 ml-13">
            配置 Castorice 的模型、性格、记忆和安全选项
          </p>
        </div>

        <div className="flex gap-6">
          {/* 侧边导航 */}
          <div className="w-48 shrink-0">
            <div className="glass rounded-2xl p-2 sticky top-6">
              {sections.map((section) => {
                const Icon = section.icon;
                const isActive = activeSection === section.id;
                return (
                  <button
                    key={section.id}
                    onClick={() => setActiveSection(section.id)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all ${
                      isActive
                        ? "bg-biolum-500/15 text-biolum-100"
                        : "text-biolum-200/50 hover:text-biolum-100 hover:bg-biolum-500/5"
                    }`}
                  >
                    <Icon
                      className={`w-4 h-5 ${isActive ? "text-biolum-300" : ""}`}
                    />
                    <span className="text-sm">{section.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 内容区 */}
          <div className="flex-1 min-w-0">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeSection}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                transition={{ duration: 0.2 }}
              >
                {renderContent()}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
