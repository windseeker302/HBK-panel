import { cn } from "@/lib/utils";

interface ProgressProps {
  value: number;
  className?: string;
  indicatorClassName?: string;
}

export function Progress({ value, className, indicatorClassName }: ProgressProps) {
  return (
    <div className={cn("relative h-3 w-full overflow-hidden rounded-full bg-secondary/80", className)}>
      <div
        className={cn(
          "h-full rounded-full bg-gradient-to-r from-primary to-[#2d8378] transition-all duration-500",
          indicatorClassName,
        )}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

