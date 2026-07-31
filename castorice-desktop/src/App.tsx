import { useEffect, useRef } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { invoke } from "@tauri-apps/api/core";
import AppLayout from "./components/ui/AppLayout";
import ChatPage from "./pages/ChatPage";
import ConsciousnessPage from "./pages/ConsciousnessPage";
import SettingsPage from "./pages/SettingsPage";
import MemoryPage from "./pages/MemoryPage";
import ToolsPage from "./pages/ToolsPage";
import SocialPage from "./pages/SocialPage";
import { useAppStore } from "./stores/appStore";
import api from "./services/api";
import wsService from "./services/ws";

function App() {
  const setAgentStatus = useAppStore((s) => s.setAgentStatus);
  const setBackendStatus = useAppStore((s) => s.setBackendStatus);
  const backendStatus = useAppStore((s) => s.backendStatus);
  const startingRef = useRef(false);

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const status = await api.status();
        setAgentStatus({
          ...status,
          running: true,
          services: {},
        });
        setBackendStatus("running");
        startingRef.current = false;
        if (!wsService.isConnected()) {
          wsService.connect();
        }
      } catch {
        if (backendStatus === "starting") {
          return;
        }
        if (!startingRef.current) {
          startingRef.current = true;
          setBackendStatus("starting");
          try {
            await invoke("start_backend");
          } catch (e) {
            console.error("启动后端失败:", e);
            setBackendStatus("error");
            startingRef.current = false;
          }
        } else {
          setBackendStatus("stopped");
        }
      }
    };

    checkBackend();
    const interval = setInterval(checkBackend, 5000);
    return () => {
      clearInterval(interval);
      wsService.disconnect();
    };
  }, [setAgentStatus, setBackendStatus, backendStatus]);

  return (
    <>
      <div className="app-bg" />
      <AnimatePresence mode="wait">
        <motion.div
          key="app"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
          className="h-full w-full"
        >
          <Routes>
            <Route path="/" element={<AppLayout />}>
              <Route index element={<Navigate to="/chat" replace />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="consciousness" element={<ConsciousnessPage />} />
              <Route path="social" element={<SocialPage />} />
              <Route path="memory" element={<MemoryPage />} />
              <Route path="tools" element={<ToolsPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </motion.div>
      </AnimatePresence>
    </>
  );
}

export default App;
