import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

type ModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
};

export const Modal = ({
  open,
  onOpenChange,
  title,
  children,
  footer,
  className,
}: ModalProps) => {
  useEffect(() => {
    if (!open) {
      return;
    }
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onOpenChange(false);
      }
    };
    globalThis.addEventListener("keydown", onKey);
    return () => globalThis.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (typeof document === "undefined" || !open) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60"
        aria-label="Close"
        onClick={() => onOpenChange(false)}
      />
      <div
        data-no-motion-disable
        className={cn(
          "relative z-10 flex w-full max-w-sm flex-col overflow-hidden rounded-lg",
          "border border-white/[0.06] bg-[#1a1a1a] shadow-2xl",
          className,
        )}
      >
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
          <h2
            id="modal-title"
            className="text-[14px] font-medium leading-tight text-[#ededed]"
          >
            {title}
          </h2>
          <button
            type="button"
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]"
            onClick={() => onOpenChange(false)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 text-[13px] text-[#ededed]">{children}</div>
        {footer ? (
          <div className="shrink-0 border-t border-white/[0.06] p-4">{footer}</div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
};
