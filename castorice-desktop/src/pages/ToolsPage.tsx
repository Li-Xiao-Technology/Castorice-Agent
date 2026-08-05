import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Wrench, Check, X, Sparkles } from "lucide-react";
import api from "@/services/api";
import type { Tool, Skill } from "@/types";

export default function ToolsPage() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tab, setTab] = useState<"tools" | "skills">("tools");

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [t, s] = await Promise.all([api.getTools(), api.getSkills()]);
      setTools(t || []);
      setSkills(s || []);
    } catch (e) {
      // 静默
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="max-w-5xl mx-auto"
      >
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-biolum-400/20 to-biolum-600/20 border border-biolum-500/20 flex items-center justify-center">
              <Wrench className="w-5 h-5 text-biolum-300" />
            </div>
            <h1 className="font-display text-3xl text-biolum-100 text-glow">工具与技能</h1>
          </div>
          <p className="text-sm text-biolum-300/50 ml-13">
            管理 Castorice 可用的工具和自动生成的技能
          </p>
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-2 mb-6">
          {[
            { id: "tools", label: "工具库", count: tools.length, icon: Wrench },
            { id: "skills", label: "技能库", count: skills.length, icon: Sparkles },
          ].map((item) => {
            const Icon = item.icon;
            const isActive = tab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setTab(item.id as any)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl transition-all ${
                  isActive
                    ? "bg-biolum-500/15 text-biolum-100 border border-biolum-500/20"
                    : "text-biolum-200/50 hover:text-biolum-100 border border-transparent hover:border-biolum-500/10"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span className="text-sm font-medium">{item.label}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${isActive ? "bg-biolum-500/20 text-biolum-200" : "bg-abyss-700 text-biolum-300/50"}`}>
                  {item.count}
                </span>
              </button>
            );
          })}
        </div>

        {/* 工具列表 */}
        {tab === "tools" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {tools.length === 0 ? (
              <div className="col-span-2 text-center py-16 glass rounded-2xl text-biolum-300/40 text-sm">
                暂无工具（请确保后端服务已启动）
              </div>
            ) : (
              tools.map((tool, i) => (
                <motion.div
                  key={tool.name}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="glass rounded-xl p-4 border border-biolum-500/10 hover:border-biolum-500/20 transition-all group"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <Wrench className="w-3.5 h-3.5 text-biolum-300/60" />
                        <h3 className="text-sm font-medium text-biolum-100 font-mono">
                          {tool.name}
                        </h3>
                      </div>
                      <p className="text-xs text-biolum-300/50 leading-relaxed">
                        {tool.description}
                      </p>
                    </div>
                    <div className="shrink-0">
                      <div className="w-5 h-5 rounded-full bg-biolum-500/20 flex items-center justify-center">
                        <Check className="w-3 h-3 text-biolum-300" strokeWidth={3} />
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))
            )}
          </div>
        )}

        {/* 技能列表 */}
        {tab === "skills" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {skills.length === 0 ? (
              <div className="col-span-2 text-center py-16 glass rounded-2xl text-biolum-300/40 text-sm">
                暂无技能（Agent 会在使用中自动沉淀技能）
              </div>
            ) : (
              skills.map((skill, i) => (
                <motion.div
                  key={skill.name}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="glass rounded-xl p-4 border border-amber-glow/10 hover:border-amber-glow/20 transition-all"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <Sparkles className="w-3.5 h-3.5 text-amber-glow/70" />
                        <h3 className="text-sm font-medium text-biolum-100">{skill.name}</h3>
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-glow/10 text-amber-glow/80 font-mono">
                          v{skill.version}
                        </span>
                      </div>
                      <p className="text-xs text-biolum-300/50 leading-relaxed">
                        {skill.description}
                      </p>
                    </div>
                  </div>
                </motion.div>
              ))
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}
