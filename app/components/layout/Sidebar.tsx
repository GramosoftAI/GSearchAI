"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { IconType } from "react-icons";
import { FiMessageSquare } from "react-icons/fi";
import { FaRobot, FaDatabase, FaChartBar, FaPlug, FaBrain } from "react-icons/fa";
import { SlSettings } from "react-icons/sl";
import { GoGraph } from "react-icons/go";
import { useTheme } from "../provider/ThemeProvider";
import ThemeModeSwitch from "../ui/ThemeModeSwitch";
import { Button } from "antd";
import { MenuUnfoldOutlined, MenuFoldOutlined } from "@ant-design/icons";

type MenuItem = {
  label: string;
  icon: IconType;
  path: string;
};

export const menuItems: MenuItem[] = [
  { label: "Bots", icon: FaRobot, path: "/dashboard/bots" },
  { label: "Knowledge Base", icon: FaDatabase, path: "/dashboard/knowledge-base" },
  { label: "Graph View", icon: GoGraph, path: "/dashboard/graph" },
  { label: "Conversations", icon: FiMessageSquare, path: "/dashboard/conversation" },
  { label: "Analytics", icon: FaChartBar, path: "/dashboard/analytics" },
  { label: "Integrations", icon: FaPlug, path: "/dashboard/integrations" },
  { label: "Settings", icon: SlSettings, path: "/dashboard/settings" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void; // Added onToggle here to handle collapse locally
  onItemClick?: () => void;
}

export default function Sidebar({ collapsed, onToggle, onItemClick }: SidebarProps) {
  const pathname = usePathname();
  const { isDark, setMode } = useTheme();
  const [mounted, setMounted] = useState(false);
 
  useEffect(() => {
    setMounted(true);
  
  }, []);

  return (
    <div
      className={`relative h-screen sticky top-0 flex flex-col transition-all duration-500 ease-[cubic-bezier(0.23,1,0.32,1)] ${
        collapsed ? "lg:w-24 w-24" : "w-full lg:w-80"
      } bg-[var(--app-surface)] text-[var(--app-text)] z-50 border-r border-[var(--app-border)] shadow-xl overflow-hidden`}
    >
      {/* 1. Header Section with Integrated Menu Toggle Button */}
      <div className={`pt-7 px-6 pb-10 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-[18px] bg-[#285d91] text-white flex items-center justify-center flex-shrink-0 shadow-lg shadow-blue-900/20">
            <FaBrain size={24} />
          </div>
          {!collapsed && (
            <span className="text-[var(--app-text)] text-2xl font-black tracking-tighter leading-none">
              Gsearch AI
            </span>
          )}
        </div>

        {/* Toggle Button Moved from Header to Sidebar Top Right */}
        {!collapsed && (
          <Button 
            type="text" 
            onClick={onToggle}
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-[var(--app-surface-muted)] text-[var(--app-text)] hover:bg-[var(--app-hover)] transition-all"
            icon={<MenuFoldOutlined className="text-lg" />}
          />
        )}
      </div>

      {/* Mini Toggle Trigger for Collapsed State */}
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

      {/* 2. Scrollable Navigation Area */}
      <nav className="flex-1 overflow-y-auto custom-scrollbar px-4 space-y-2">
        {menuItems.map((item) => {
          const isActive = pathname === item.path;
          return (
            <Link
              key={item.path}
              href={item.path}
              onClick={onItemClick}
              className={`group relative flex items-center gap-4 px-4 py-3.5 rounded-2xl transition-all duration-300 overflow-hidden ${
                isActive 
                  ? "bg-[#285d91] text-white shadow-lg shadow-blue-900/20" 
                  : "text-slate-400 hover:bg-slate-50 hover:text-[#285d91]"
              } ${collapsed ? "justify-center" : "justify-start"}`}
            >
              {isActive && !collapsed && (
                <div className="absolute left-0 top-1/4 bottom-1/4 w-1 bg-white rounded-r-full" />
              )}
              
              <item.icon className={`flex-shrink-0 text-xl transition-transform duration-300 ${isActive ? "scale-110" : "group-hover:scale-110"}`} />
              
              {!collapsed && (
                <span className={`text-[17px] font-bold tracking-tight transition-all duration-300 ${isActive ? "ml-1" : ""}`}>
                  {item.label}
                </span>
              )}
            </Link>
          );
        })}
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
