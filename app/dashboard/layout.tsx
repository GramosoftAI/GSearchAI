"use client";

import { useState,useEffect } from "react";
import Sidebar from "../components/layout/Sidebar";
import Header from "../components/layout/Header";
import { Drawer } from "antd";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Desktop: collapsed/expanded sidebar
  const [collapsed, setCollapsed] = useState(true);
  const [width, setWidth] = useState(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleResize = () => {
      setWidth(window.innerWidth);
    };
    handleResize(); // initial value
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 769) {
        setCollapsed(true);
      }
    };
    handleResize(); // initial check
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  return (
    <div className="h-screen flex w-full relative bg-[var(--app-surface-muted)] overflow-hidden transition-colors duration-500">
      {/* Premium Background Decorative Elements */}
      <div className="fixed top-0 left-0 w-full h-full pointer-events-none overflow-hidden z-0">
        <div className="absolute top-[-10%] right-[-10%] w-[50%] h-[50%] bg-[#285d91]/5 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-50/20 rounded-full blur-[100px]" />
      </div>

      {/* Desktop Inline Sidebar - Hidden on mobile screens */}
      <div className="hidden sm:block flex-shrink-0 relative z-10 transition-all duration-500 border-r border-[var(--app-border)]">
        <Sidebar collapsed={collapsed}
          onToggle={() => setCollapsed((prev) => !prev)}
        />
      </div>

      {/* Mobile Drawer Sidebar - Shown on menu click, takes full screen width */}
      <Drawer
        placement="left"
        onClose={() => setMobileMenuOpen(false)}
        open={mobileMenuOpen}
        styles={{ 
          body: { padding: 0, background: 'var(--app-surface)' },
          content: { background: 'var(--app-surface)' }
        }}
        width="100%"
        closeIcon={null}
      >
        <Sidebar collapsed={false} onToggle={() => setMobileMenuOpen(false)} onItemClick={() => setMobileMenuOpen(false)} />
      </Drawer>

      {/* Main column - Independently Scrollable */}
      <div className="flex-1 flex flex-col relative z-10 h-full overflow-hidden">
        <Header onMenuClick={() => setMobileMenuOpen(true)} />

        {/* Page content - Scrollable area */}
        <main className="flex-1 w-full p-0 md:p-0 xl:p-0 overflow-y-auto custom-dashboard-scroll animate-in fade-in slide-in-from-bottom-4 duration-1000">
          <div className="max-w-[1600px] mx-auto">
            {children}
          </div>
        </main>
      </div>

      <style jsx global>{`
        :root {
          /* New Professional White & Blue Palette */
          --color-blue: #285d91;
          --color-white: #ffffff;
          
          --app-primary: var(--color-blue);
          --app-secondary: var(--color-white);
          
          --app-surface: #ffffff;
          --app-surface-muted: #f9fbff;
          --app-border: #e2e8f0;
          --app-text: #0f172a;
          --app-text-muted: #64748b;
          --app-text-soft: #94a3b8;
          --app-active-bg: #eff6ff;
          --app-hover: #f1f5f9;
        }

        [data-theme='dark'] {
          --app-surface: #0a0f1d;
          --app-surface-muted: #050810;
          --app-border: #1e293b;
          --app-text: #f8fafc;
          --app-text-muted: #94a3b8;
          --app-text-soft: #475569;
          --app-active-bg: #1e293b;
          --app-hover: #1e293b;
          
          /* Force White elements to Dark in Dark Mode */
          --color-white: #0a0f1d;
        }

        body {
          background-color: var(--app-surface-muted);
          color: var(--app-text);
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          transition: background-color 0.3s ease, color 0.3s ease;
        }

        /* Modern Scrollbar */
        ::-webkit-scrollbar {
          width: 6px;
          height: 6px;
        }
        ::-webkit-scrollbar-track {
          background: transparent;
        }
        ::-webkit-scrollbar-thumb {
          background: var(--app-border);
          border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
          background: var(--app-text-soft);
        }

        .custom-dashboard-scroll::-webkit-scrollbar {
          width: 4px;
        }
        .custom-dashboard-scroll::-webkit-scrollbar-thumb {
          background: var(--app-border);
          opacity: 0.5;
        }

        [data-theme='dark'] ::-webkit-scrollbar-thumb {
          background: #1e293b;
        }

        /* Ant Design Overrides to match Theme */
        .ant-typography {
          color: var(--app-text) !important;
        }
        .ant-card {
          background: var(--app-surface) !important;
          border-color: var(--app-border) !important;
        }
        .ant-btn-primary {
          background-color: #285d91 !important;
          border-color: #285d91 !important;
        }
        .ant-btn-primary:hover {
          background-color: #1d4d7c !important;
          border-color: #1d4d7c !important;
        }
        .ant-modal-content {
          background: var(--app-surface) !important;
          color: var(--app-text) !important;
        }

        /* Premium Notification Styling */
        .ant-notification-notice {
          border-radius: 24px !important;
          padding: 20px 24px !important;
          box-shadow: 0 20px 40px rgba(0,0,0,0.1) !important;
          border: 1px solid var(--app-border) !important;
          background: var(--app-surface) !important;
          backdrop-filter: blur(10px);
          overflow: hidden !important;
        }

        .custom-toast-success {
          border-left: 6px solid #10b981 !important;
        }
        .custom-toast-success .ant-notification-notice-message {
          color: #10b981 !important;
          font-weight: 900 !important;
          text-transform: uppercase !important;
          letter-spacing: 0.1em !important;
          font-size: 12px !important;
        }
        .custom-toast-success .ant-notification-notice-description {
          color: var(--app-text) !important;
          font-weight: 700 !important;
          font-size: 14px !important;
        }

        .custom-toast-error {
          border-left: 6px solid #ef4444 !important;
        }
        .custom-toast-error .ant-notification-notice-message {
          color: #ef4444 !important;
          font-weight: 900 !important;
          text-transform: uppercase !important;
          letter-spacing: 0.1em !important;
          font-size: 12px !important;
        }
        .custom-toast-error .ant-notification-notice-description {
          color: var(--app-text) !important;
          font-weight: 700 !important;
          font-size: 14px !important;
        }

        [data-theme='dark'] .ant-notification-notice {
          background: rgba(10, 15, 29, 0.8) !important;
          border-color: rgba(255, 255, 255, 0.1) !important;
        }
      `}</style>
    </div>
  );
}
