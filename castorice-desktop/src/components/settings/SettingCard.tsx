import { motion } from "framer-motion";
import { ReactNode } from "react";

interface SettingCardProps {
  title: string;
  description?: string;
  children: ReactNode;
  icon?: ReactNode;
}

export default function SettingCard({
  title,
  description,
  children,
  icon,
}: SettingCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass rounded-2xl p-6"
    >
      <div className="flex items-start gap-3 mb-5">
        {icon && (
          <div className="w-9 h-9 rounded-xl bg-biolum-500/10 border border-biolum-500/20 flex items-center justify-center shrink-0">
            {icon}
          </div>
        )}
        <div>
          <h3 className="font-display text-lg text-biolum-100">{title}</h3>
          {description && (
            <p className="text-xs text-biolum-300/50 mt-0.5">{description}</p>
          )}
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </motion.div>
  );
}
