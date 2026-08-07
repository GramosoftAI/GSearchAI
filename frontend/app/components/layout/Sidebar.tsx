"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { IconType } from "react-icons";
import { FiMessageSquare } from "react-icons/fi";
import { FaRobot, FaDatabase, FaChartBar, FaPlug, FaBrain, FaFileAlt } from "react-icons/fa";
import { SlSettings } from "react-icons/sl";
import { GoGraph } from "react-icons/go";
import { useTheme } from "../provider/ThemeProvider";
import ThemeModeSwitch from "../ui/ThemeModeSwitch";
import { Button} from "antd";
import { MenuUnfoldOutlined, MenuFoldOutlined } from "@ant-design/icons";
import { Home, Users,ThumbsUp, CreditCard, Settings, DollarSign, AlertCircle, Shield } from "lucide-react";
import { useStore } from "../../hooks/useStore";

type MenuItem = {
  label: string;
  icon: IconType;
  path: string;
};

export const menuItems: MenuItem[] = [
  { label: "Bots", icon: FaRobot, path: "/dashboard/bots" },
  { label: "Knowledge Base", icon: FaDatabase, path: "/dashboard/knowledge-base" },
  { label: "Knowledge Files", icon: FaFileAlt, path: "/dashboard/knowledge-base-files" },
  { label: "Graph View", icon: GoGraph, path: "/dashboard/graph" },
  { label: "Conversations", icon: FiMessageSquare, path: "/dashboard/conversation" },
  { label: "Analytics", icon: FaChartBar, path: "/dashboard/analytics" },
  { label: "Integrations", icon: FaPlug, path: "/dashboard/integrations" },
  { label: "Settings", icon: SlSettings, path: "/dashboard/settings" },
];

export const adminMenuItems = [
  { label: "Overview", icon: Home, path: "/dashboard/admin/overview" },
  { label: "User Management", icon: Users, path: "/dashboard/admin/users" },
  { label: "Feedback", icon: ThumbsUp, path: "/dashboard/admin/feedback" },
  { label: "Token Usage & Costs", icon: CreditCard, path: "/dashboard/admin/billing" },
  { label: "Global Settings", icon: Settings, path: "/dashboard/admin/settings" },
  { label: "Custom Requests", icon: DollarSign, path: "/dashboard/admin/requests" },
  { label: "Error Logs", icon: AlertCircle, path: "/dashboard/admin/logs" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void; 
  onItemClick?: () => void;
}

export default function Sidebar({ collapsed, onToggle, onItemClick }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { isDark, setMode } = useTheme();
  const [mounted, setMounted] = useState(false);
  const { isAdminMode, setIsAdminMode } = useStore();
  const [isAdminUser, setIsAdminUser] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsAdminUser(localStorage.getItem("isAdmin") === "true");
  }, []);

  return (
    <div
      className={`relative h-screen sticky top-0 flex flex-col transition-all duration-500 ease-[cubic-bezier(0.23,1,0.32,1)] ${
        collapsed ? "lg:w-24 w-24" : "w-full lg:w-80"
      } bg-[var(--app-surface)] text-[var(--app-text)] z-50 border-r border-[var(--app-border)] shadow-xl overflow-hidden`}
    >
      <div className={`pt-7 px-6 pb-10 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
        <div className="flex items-center gap-4">
          {collapsed ? (
            isAdminMode ? (
              <div 
                className="w-12 h-12 rounded-[18px] text-white flex items-center justify-center flex-shrink-0 shadow-lg shadow-[var(--app-primary)]/20 animate-in zoom-in duration-300"
                style={{ backgroundColor: "var(--app-primary)" }}
              >
                <Shield size={24} style={{ color: "#ffffff", fill: "#ffffff" }} />
              </div>
            ) : (
              <div className="w-12 h-12 rounded-[18px] flex items-center justify-center flex-shrink-0 shadow-lg shadow-[var(--app-primary)]/20 overflow-hidden">
                <img src="/512_512.png" alt="Gsearch AI Logo" className="w-full h-full object-contain" />
              </div>
            )
          ) : (
            isAdminMode ? (
              <>
                <div 
                  className="w-12 h-12 rounded-[18px] text-white flex items-center justify-center flex-shrink-0 shadow-lg shadow-[var(--app-primary)]/20 animate-in zoom-in duration-300"
                  style={{ backgroundColor: "var(--app-primary)" }}
                >
                  <Shield size={24} style={{ color: "#ffffff", fill: "#ffffff" }} />
                </div>
                <span className="text-[var(--app-text)] text-2xl font-black tracking-tighter leading-none animate-in fade-in duration-300">
                  Admin Portal
                </span>
              </>
            ) : (
              <img 
                src={isDark ? "/GSearchAI Logos White.svg" : "/Group 1597883327.svg"} 
                alt="Gsearch AI" 
                className="h-10 max-w-[180px] object-contain animate-in fade-in duration-300" 
              />
            )
          )}
        </div>

        {!collapsed && (
          <Button 
            type="text" 
            onClick={onToggle}
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-[var(--app-surface-muted)] text-[var(--app-text)] hover:bg-[var(--app-hover)] transition-all"
            icon={<MenuFoldOutlined className="text-lg" />}
          />
        )}
      </div>

      {collapsed && (
        <div className="flex justify-center pb-4 px-4">
          <Button 
            type="text" 
            onClick={onToggle}
            className="flex items-center justify-center w-12 h-12 rounded-2xl bg-[var(--app-surface-muted)] text-[var(--app-text)] hover:bg-[var(--app-hover)] transition-all"
            icon={<MenuUnfoldOutlined className="text-xl" />}
          />
        </div>
      )}

      <nav className="flex-1 overflow-y-auto custom-scrollbar px-4 space-y-2">
        {isAdminMode ? (
          adminMenuItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link
                key={item.path}
                href={item.path}
                onClick={(e) => {
                  if (onItemClick) onItemClick();
                }}
                className={`group relative flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 overflow-hidden ${
                  isActive 
                    ? "" 
                    : "text-[var(--app-text-soft)] hover:bg-[var(--app-hover)] hover:text-[var(--app-primary)]"
                } ${collapsed ? "justify-center" : "justify-start"}`}
                style={
                  isActive
                    ? {
                        backgroundColor: "var(--app-primary)",
                        color: "#ffffff",
                        boxShadow: "0 10px 15px -3px rgba(15, 181, 161, 0.25), 0 4px 6px -2px rgba(15, 181, 161, 0.25)",
                      }
                    : undefined
                }
              >
                {isActive && !collapsed && (
                  <div className="absolute left-0 top-1/4 bottom-1/4 w-1 bg-white rounded-r-full" />
                )}
                
                <item.icon 
                  className={`flex-shrink-0 text-xl transition-transform duration-300 ${
                    isActive 
                      ? "scale-110" 
                      : "text-[var(--app-text-soft)] group-hover:scale-110 group-hover:text-[var(--app-primary)]"
                  }`}
                  style={isActive ? { color: "#ffffff" } : undefined}
                />
                
                {!collapsed && (
                  <span 
                    className={`text-[17px] font-bold tracking-tight transition-all duration-300 ${
                      isActive 
                        ? "ml-1" 
                        : "text-[var(--app-text-soft)] group-hover:text-[var(--app-primary)]"
                    }`}
                    style={isActive ? { color: "#ffffff" } : undefined}
                  >
                    {item.label}
                  </span>
                )}
              </Link>
            );
          })
        ) : (
          <>
            {(() => {
              const itemsToRender = [...menuItems];
              if (isAdminUser) {
                const settingsIndex = itemsToRender.findIndex(item => item.path === "/dashboard/settings");
                if (settingsIndex !== -1) {
                  itemsToRender.splice(settingsIndex, 0, {
                    label: "Admin Portal",
                    icon: Shield as any,
                    path: "admin-toggle"
                  });
                } else {
                  itemsToRender.push({
                    label: "Admin Portal",
                    icon: Shield as any,
                    path: "admin-toggle"
                  });
                }
              }

              return itemsToRender.map((item) => {
                const isSpecialAdmin = item.path === "admin-toggle";
                const isActive = pathname === item.path;
                
                if (isSpecialAdmin) {
                  return (
                    <Link
                      key="admin-toggle"
                      href="/dashboard/admin/overview"
                      onClick={() => {
                        setIsAdminMode(true);
                        if (onItemClick) onItemClick();
                      }}
                      className={`group relative flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 overflow-hidden ${
                        isActive 
                          ? "" 
                          : "text-[var(--app-text-soft)] hover:bg-[var(--app-hover)] hover:text-[var(--app-primary)]"
                      } ${collapsed ? "justify-center" : "justify-start"}`}
                    >
                      <Shield 
                        className="flex-shrink-0 text-xl transition-transform duration-300 text-[var(--app-text-soft)] group-hover:scale-110 group-hover:text-[var(--app-primary)]"
                      />
                      {!collapsed && (
                        <span className="text-[17px] font-bold tracking-tight text-[var(--app-text-soft)] group-hover:text-[var(--app-primary)]">
                          Admin Portal
                        </span>
                      )}
                    </Link>
                  );
                }

                return (
                  <Link
                    key={item.path}
                    href={item.path}
                    onClick={onItemClick}
                    className={`group relative flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 overflow-hidden ${
                      isActive 
                        ? "" 
                        : "text-[var(--app-text-soft)] hover:bg-[var(--app-hover)] hover:text-[var(--app-primary)]"
                    } ${collapsed ? "justify-center" : "justify-start"}`}
                    style={
                      isActive
                        ? {
                            backgroundColor: "var(--app-primary)",
                            color: "#ffffff",
                            boxShadow: "0 10px 15px -3px rgba(15, 181, 161, 0.25), 0 4px 6px -2px rgba(15, 181, 161, 0.25)",
                          }
                        : undefined
                    }
                  >
                    {isActive && !collapsed && (
                      <div className="absolute left-0 top-1/4 bottom-1/4 w-1 bg-white rounded-r-full" />
                    )}
                    
                    <item.icon 
                      className={`flex-shrink-0 text-xl transition-transform duration-300 ${
                        isActive 
                          ? "scale-110" 
                          : "text-[var(--app-text-soft)] group-hover:scale-110 group-hover:text-[var(--app-primary)]"
                      }`}
                      style={isActive ? { color: "#ffffff" } : undefined}
                    />
                    
                    {!collapsed && (
                      <span 
                        className={`text-[17px] font-bold tracking-tight transition-all duration-300 ${
                          isActive 
                            ? "ml-1" 
                            : "text-[var(--app-text-soft)] group-hover:text-[var(--app-primary)]"
                        }`}
                        style={isActive ? { color: "#ffffff" } : undefined}
                      >
                        {item.label}
                      </span>
                    )}
                  </Link>
                );
              });
            })()}
          </>
        )}
      </nav>

      {/* 3. Footer Section (Only Theme Switch remaining) */}
      <div className="mt-auto border-t border-[var(--app-border)] p-6 flex flex-col gap-5 bg-[var(--app-surface)] relative z-20">
        <div className={`flex items-center gap-3 ${collapsed ? "justify-center" : "justify-between"} px-2`}>
          {!collapsed && mounted && (
            <span className="text-[10px] font-black uppercase tracking-widest text-slate-400 opacity-50">
              {isDark ? "Dark Appearance" : "Light Appearance"}
            </span>
          )}
          <ThemeModeSwitch checked={isDark} onChange={(checked) => setMode(checked ? "dark" : "light")} />
        </div>
      </div>

      <style jsx>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 0px;
          background: transparent;
        }
        .custom-scrollbar {
          scrollbar-width: none;
          -ms-overflow-style: none;
          }
      `}</style>
    </div>
  );
}
