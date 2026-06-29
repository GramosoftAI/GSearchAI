"use client";

import { menuItems } from "./Sidebar";
import { Avatar, Button } from "antd";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { deleteCookie } from "../../config/cookies";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import { MenuOutlined } from "@ant-design/icons";

interface HeaderProps {
  onMenuClick?: () => void;
}

export default function Header({ onMenuClick }: HeaderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [userName, setUserName] = useState("User");

  useEffect(() => {
    const storedName = localStorage.getItem("userName");
    if (storedName) {
      setUserName(storedName);
    }
  }, []);

  const handleLogout = () => {
    localStorage.clear();
    deleteCookie("AUTH_TOKEN");
    router.push("/login");
  };

  const getInitials = (name: string) => {
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  };

  const currentPage = menuItems.find(item => item.path === pathname)?.label || "Dashboard";



  const profileDropdownItems: MenuProps['items'] = [
    {
      key: 'user_info',
      label: (
        <div className="flex flex-col px-2 py-2 min-w-[160px] border-b border-[var(--app-border)] mb-1">
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--app-text-muted)] opacity-50">
            Account
          </span>
          <span className="text-sm font-black text-[var(--app-text)] tracking-tight mt-1 truncate max-w-[150px]">
            {userName}
          </span>
          {/* <span className="text-[9px] font-bold text-[#285d91] dark:text-blue-400 mt-0.5">
            Workspace Admin
          </span> */}
        </div>
      ),
      disabled: true, // Making it a clean display card, non-clickable
    },
    {
      key: 'logout',
      danger: true,
      label: (
        <div className="flex items-center gap-3 px-2 py-2 font-bold text-xs tracking-tight">
          {/* Modern minimal exit icon */}
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor" className="w-4 h-4">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
          </svg>
          <span>Sign Out</span>
        </div>
      ),
      onClick: handleLogout,
    },
  ];
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const handleResize = () => {
      setWidth(window.innerWidth);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return (
    <header className="sticky top-0 z-[50] w-full h-24 flex flex-col justify-center bg-[var(--app-surface)]/80 backdrop-blur-xl border-b border-[var(--app-border)] px-6 md:px-10 transition-all">
      <div className="flex items-center justify-between w-full max-w-[1600px] mx-auto gap-4">

        {/* LEFT SIDE: Workspace Info & Mobile Hamburger */}
        <div className="flex items-center gap-4 shrink-0">
          {/* Hamburger icon for mobile view only (width < 640) */}
          {width > 0 && width < 640 && (
            <Button 
              type="text"
              icon={<MenuOutlined className="text-xl text-[var(--app-text)]" />}
              onClick={onMenuClick}
              className="flex items-center justify-center w-10 h-10 rounded-xl bg-[var(--app-hover)] relative z-50 shrink-0"
            />
          )}

          <div className="flex flex-col">
            {(width > 568) && <div className="flex items-center gap-2 text-[var(--app-text-muted)] font-black text-[10px] uppercase tracking-[0.2em]">
              Workspace / {currentPage}
            </div>}
            {(width > 568) && <h2 className="text-[var(--app-text)] font-black text-xl md:text-2xl tracking-tighter leading-none mt-1">
              {currentPage}
            </h2>}
          </div>
        </div>

        {/* RIGHT SIDE: Profile Card with Integrated Logout Button */}
        <div className="flex items-center shrink-0 select-none">
          <Dropdown
            menu={{ items: profileDropdownItems }}
            trigger={['click']}
            placement="bottomRight"
            classNames="premium-avatar-dropdown"
          >
            <div className="relative cursor-pointer group p-[2px]">
              <div className="absolute inset-0 rounded-full bg-gradient-to-tr from-[#285d91] via-sky-400 to-indigo-500 opacity-0 group-hover:opacity-100 group-hover:rotate-180 transition-all duration-700 ease-out p-[1.5px]" />
              <div className="p-1 bg-[var(--app-surface)] rounded-full relative z-10 transition-transform duration-300 active:scale-95">
                <Avatar
                  className="bg-gradient-to-br from-[#285d91] to-[#163a5f] text-white font-extrabold tracking-wider border border-white/20 dark:border-zinc-800 shadow-md group-hover:shadow-lg transition-all"
                  size={46}
                >
                  {getInitials(userName)}
                </Avatar>
              </div>
              <span className="absolute bottom-1 right-1 flex h-3.5 w-3.5 z-20">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-emerald-500 border-2 border-[var(--app-surface)] shadow-md"></span>
              </span>
            </div>
          </Dropdown>
        </div>

      </div>
    </header>
  );
}
