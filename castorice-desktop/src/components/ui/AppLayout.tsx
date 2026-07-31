import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  MessageSquare,
  Brain,
  Database,
  Wrench,
  Settings,
  Sparkles,
  PanelLeftClose,
  PanelLeft,
  Users,
} from "lucide-react";
import Sidebar from "../sidebar/SessionList";
import ServiceStatus from "../sidebar/ServiceStatus";
import NotificationCenter from "./NotificationCenter";
import { useAppStore } from "@/stores/appStore";

const navItems = [
  { id: "chat", label: "对话", icon: MessageSquare, path: "/chat" },
  { id: "consciousness", label: "意识流", icon: Brain, path: "/consciousness" },
  { id: "social", label: "社交", icon: Users, path: "/social" },
  { id: "memory", label: "记忆", icon: Database, path: "/memory" },
  { id: "tools", label: "工具", icon: Wrench, path: "/tools" },
  { id: "settings", label: "设置", icon: Settings, path: "/settings" },
];

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const activeView = useAppStore((s) => s.activeView);
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const setActiveView = useAppStore((s) => s.setActiveView);

  return (
    <div className="h-full w-full flex">
      {/* 左侧导航 */}
      <motion.nav
        initial={false}
        animate={{ width: sidebarCollapsed ? 64 : 240 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="glass-strong border-r border-biolum-500/10 flex flex-col h-full relative overflow-hidden"
      >
        {/* Logo */}
        <div className="h-16 flex items-center px-4 border-b border-biolum-500/10 shrink-0">
          <motion.div
            animate={{ rotate: [0, 5, -5, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
            className="w-9 h-9 rounded-xl bg-gradient-to-br from-biolum-400 to-biolum-600 flex items-center justify-center shadow-glow shrink-0"
          >
            <Sparkles className="w-5 h-5 text-abyss-950" strokeWidth={2.5} />
          </motion.div>
          {!sidebarCollapsed && (
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="ml-3 overflow-hidden"
            >
              <h1 className="font-display text-xl font-semibold text-biolum-100 text-glow leading-none">
                Castorice
              </h1>
              <p className="text-[10px] text-biolum-300/50 mt-0.5 tracking-widest uppercase">
                Conscious AI
              </p>
            </motion.div>
          )}
        </div>

        {/* 导航项 */}
        <div className="flex-1 py-3 flex flex-col gap-1 px-2 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <button
                key={item.id}
                onClick={() => {
                  navigate(item.path);
                  setActiveView(item.id as any);
                }}
                className={`group relative flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300 ${
                  isActive
                    ? "bg-biolum-500/15 text-biolum-100"
                    : "text-biolum-200/50 hover:text-biolum-100 hover:bg-biolum-500/5"
                }`}
                title={sidebarCollapsed ? item.label : undefined}
              >
                {isActive && (
                  <motion.div
                    layoutId="navActive"
                    className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 rounded-r-full bg-biolum-400 shadow-glow"
                  />
                )}
                <Icon
                  className={`w-5 h-5 shrink-0 transition-all ${
                    isActive ? "text-biolum-300" : "group-hover:text-biolum-300"
                  }`}
                  strokeWidth={isActive ? 2.2 : 1.8}
                />
                {!sidebarCollapsed && (
                  <span className="text-sm font-medium truncate">{item.label}</span>
                )}
              </button>
            );
          })}

          {!sidebarCollapsed && (
            <>
              <div className="h-px bg-biolum-500/10 my-3" />
              <Sidebar />
            </>
          )}
        </div>

        {/* 底部状态 + 折叠按钮 */}
        <div className="shrink-0 border-t border-biolum-500/10 p-3">
          {!sidebarCollapsed && <ServiceStatus />}
          <button
            onClick={toggleSidebar}
            className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-biolum-300/40 hover:text-biolum-200 hover:bg-biolum-500/5 transition-all"
          >
            {sidebarCollapsed ? (
              <PanelLeft className="w-4 h-4" />
            ) : (
              <>
                <PanelLeftClose className="w-4 h-4" />
                <span className="text-xs">收起侧栏</span>
              </>
            )}
          </button>
        </div>
      </motion.nav>

      {/* 主内容区 */}
      <main className="flex-1 h-full overflow-hidden relative">
        {/* 右上角工具栏 */}
        <div className="absolute top-4 right-4 z-40 flex items-center gap-2">
          <NotificationCenter />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
