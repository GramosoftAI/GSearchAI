"use client"
import { Button} from 'antd'
import { useRouter } from 'next/navigation'
import { routes } from '@/app/services/routes'

export default function NavBar() {
  const router = useRouter();
  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-slate-200/50 bg-white/70 backdrop-blur-xl transition-all duration-300">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
        <div className="flex items-center gap-3 cursor-pointer group" onClick={() => router.push("/")}>
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#2879f3] shadow-lg shadow-blue-500/20 transition-transform group-hover:scale-110">
            <span className="text-sm font-black text-white">GS</span>
          </div>
          <span className="text-2xl font-black tracking-tighter text-[#0f172a]">Gsearch AI</span>
        </div>

        <nav className="hidden md:flex items-center gap-10">
          {['Features', 'Pricing', 'Docs'].map((item) => (
            <a 
              key={item} 
              href={`#${item.toLowerCase()}`} 
              className="text-sm font-bold text-slate-500 transition-colors hover:text-[#2879f3]"
            >
              {item}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-4">
          <Button 
            type="text" 
            onClick={() => router.push(routes.login)} 
            className="!text-slate-600 !font-bold !text-sm hover:!text-[#2879f3]"
          >
            Log In
          </Button>
          <Button 
            onClick={() => router.push(routes.register)} 
            className="!h-11 !px-6 !rounded-xl !bg-[#2879f3] !border-none !text-white !font-bold !text-sm hover:!scale-105 transition-all shadow-lg shadow-blue-500/20"
          >
            Sign Up
          </Button>
        </div>
      </div>
    </header>
  )
}
