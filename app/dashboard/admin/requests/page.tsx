"use client";

import { DollarSign } from "lucide-react";

export default function AdminRequestsPage() {
  return (
    <div className="min-h-[70vh] flex items-center justify-center p-8">
      <div className="flex flex-col items-center justify-center text-center p-12 bg-[var(--app-surface)] border border-[var(--app-border)]/60 rounded-3xl shadow-xl max-w-lg w-full relative overflow-hidden animate-in zoom-in duration-500">
        <div className="absolute top-[-20%] right-[-20%] w-[60%] h-[60%] bg-blue-500/5 rounded-full blur-[60px]" />
        
        <div className="w-20 h-20 rounded-2xl bg-blue-50 dark:bg-blue-950/20 text-blue-600 flex items-center justify-center mb-6 shadow-md">
          <DollarSign size={40} />
        </div>
        <h2 className="text-[var(--app-text)] font-black text-2xl md:text-3xl tracking-tight mb-3">
          Custom Requests
        </h2>
        <p className="text-[var(--app-text-soft)] font-medium text-sm md:text-base max-w-sm leading-relaxed mb-6">
          This Custom Requests feature is currently under development. Stay tuned for updates!
        </p>
        <div className="w-full bg-[var(--app-surface-muted)] py-3 px-4 rounded-xl border border-[var(--app-border)]/40 flex items-center justify-between text-xs font-bold uppercase tracking-wider text-[var(--app-text-soft)]">
          <span>Status</span>
          <span className="text-blue-600 dark:text-blue-400">Coming Soon</span>
        </div>
      </div>
    </div>
  );
}
