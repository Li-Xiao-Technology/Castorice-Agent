import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen,
  User,
  Sprout,
  Target,
} from "lucide-react";
import KnowledgePage from "./KnowledgePage";
import PersonalityPage from "./PersonalityPage";
import GrowthPage from "./GrowthPage";
import GoalsPage from "./GoalsPage";

const tabs = [
  { id: "knowledge", label: "知识卡片", icon: BookOpen, color: "from-sky-400 to-blue-600" },
  { id: "personality", label: "人格画像", icon: User, color: "from-fuchsia-400 to-purple-600" },
  { id: "growth", label: "成长轨迹", icon: Sprout, color: "from-emerald-400 to-teal-600" },
  { id: "goals", label: "目标管理", icon: Target, color: "from-amber-400 to-orange-600" },
];

export default function SelfGrowthPage() {
  const [activeTab, setActiveTab] = useState("knowledge");

  const renderContent = () => {
    switch (activeTab) {
      case "knowledge":
        return <KnowledgePage />;
      case "personality":
        return <PersonalityPage />;
      case "growth":
        return <GrowthPage />;
      case "goals":
        return <GoalsPage />;
      default:
        return null;
    }
  };

  const activeTabData = tabs.find((t) => t.id === activeTab)!;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* 头部 */}
      <div className="shrink-0 px-6 pt-6 pb-2">
        <div className="flex items-center gap-3 mb-4">
          <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${activeTabData.color} flex items-center justify-center shadow-glow`}>
            <activeTabData.icon className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="font-display text-2xl font-semibold text-biolum-100 text-glow">
              自我成长
            </h1>
            <p className="text-sm text-biolum-300/50 mt-0.5">
              知识、人格、成长轨迹、目标——Agent 的完整自我画像
            </p>
          </div>
        </div>

        {/* Tab 导航 */}
        <div className="flex gap-1 p-1 rounded-xl bg-abyss-800/40 border border-biolum-500/10 w-fit">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  isActive
                    ? `bg-gradient-to-r ${tab.color} text-abyss-950 shadow-glow`
                    : "text-biolum-300/60 hover:text-biolum-100 hover:bg-abyss-700/50"
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="h-full"
          >
            {renderContent()}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
