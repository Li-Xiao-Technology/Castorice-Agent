import { ReactNode } from "react";

interface SettingRowProps {
  label: string;
  description?: string;
  children: ReactNode;
}

export default function SettingRow({
  label,
  description,
  children,
}: SettingRowProps) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-biolum-100">{label}</div>
        {description && (
          <div className="text-xs text-biolum-300/50 mt-0.5">{description}</div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
