interface SliderProps {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  unit?: string;
  displayValue?: string;
  labels?: string[];
}

export default function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  unit = "",
  displayValue,
  labels,
}: SliderProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-biolum-200/60 font-mono">
          {displayValue !== undefined
            ? displayValue : `${value}${unit}`}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-biolum-400 h-1.5"
      />
      {labels && labels.length >= 2 && (
        <div className="flex justify-between mt-1 text-[10px] text-biolum-300/40">
          {labels.map((l, i) => (
            <span key={i}>{l}</span>
          ))}
        </div>
      )}
    </div>
  );
}
