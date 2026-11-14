"use client";

import React, { useState, useEffect } from 'react';
import { useRouter } from "next/navigation";
import Script from "next/script";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "../hooks/useLogin";
import { routes } from "../../../services/routes";
import BrandGlyph from "../../../components/landing/BrandGlyph";

declare global {
  interface Window {
    google?: any;
  }
}

export default function LoginForm() {
  const router = useRouter();
  const { login, loginWithGoogle, error, isSubmitting } = useLogin();
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);

  const initGoogleBtn = () => {
    if (typeof window !== "undefined" && window.google?.accounts?.id) {
      const clientId =
        process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ||
        "370095760215-9airu0dgt91c4qerggvh66ip693uh8sq.apps.googleusercontent.com";

      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (response: any) => {
          if (response?.credential) {
            loginWithGoogle(response.credential);
          }
        },
      });

      const googleBtnContainer = document.getElementById("googleSignInDiv");
      if (googleBtnContainer) {
        googleBtnContainer.innerHTML = "";
        window.google.accounts.id.renderButton(googleBtnContainer, {
          theme: "outline",
          size: "large",
          width: 400,
        });
      }
    }
  };

  useEffect(() => {
    initGoogleBtn();
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    login(formData);
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#f3f4f6] font-sans p-4 relative overflow-hidden">
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={initGoogleBtn}
      />

      <div className="w-full max-w-[460px] relative">
        {/* Decorative Background Circles */}
        <div className="w-32 h-32 rounded-full bg-[#0fb5a1] absolute -top-5 -left-5 z-0 opacity-90 pointer-events-none" />
        <div className="w-32 h-32 rounded-full bg-[#f37e10] absolute -bottom-5 -right-5 z-0 opacity-90 pointer-events-none" />

        <form
          className="w-full bg-white rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.06)] border border-[#e5e7eb] px-8 py-9 sm:px-10 sm:py-10 flex flex-col items-center relative z-10"
          onSubmit={handleSubmit}
        >
          {/* Logo */}
          <div className="mb-6 flex justify-center">
            <BrandGlyph height={42} />
          </div>

          {/* Top Segmented Tab Switcher: Log In / Sign Up */}
          <div className="flex bg-[#f1f5f9] p-1 rounded-2xl mb-6 w-full">
            <button
              type="button"
              className="flex-1 py-2.5 text-sm font-semibold rounded-xl bg-[#0fb5a1] text-white shadow-sm transition-all"
            >
              Log In
            </button>
            <button
              type="button"
              onClick={() => router.push(routes.register)}
              className="flex-1 py-2.5 text-sm font-semibold rounded-xl text-[#475569] hover:text-[#0fb5a1] transition-all"
            >
              Sign Up
            </button>
          </div>

          {/* Google Sign-In Button */}
          <div className="relative w-full mb-4 overflow-hidden rounded-xl">
            {/* Custom UI Button matching reference */}
            <div className="w-full flex items-center justify-center gap-3 py-3 px-4 bg-white border border-[#cbd5e1] hover:bg-slate-50/80 rounded-xl text-sm font-semibold text-[#0f172a] shadow-sm transition-all cursor-pointer">
              <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                />
              </svg>
              <span>Continue with Google</span>
            </div>

            {/* Invisible Google Sign-In Div layered right on top */}
            <div
              id="googleSignInDiv"
              className="absolute inset-0 flex justify-center items-center cursor-pointer scale-125"
              style={{ opacity: 0.001 }}
            />
          </div>

          {/* Divider */}
          <div className="flex items-center w-full my-3">
            <div className="flex-1 h-[1px] bg-[#e2e8f0]" />
            <span className="px-4 text-xs font-semibold text-[#94a3b8] uppercase tracking-wider">OR</span>
            <div className="flex-1 h-[1px] bg-[#e2e8f0]" />
          </div>

          {error && (
            <p className="text-red-500 text-xs font-semibold mb-2 text-center w-full">{error}</p>
          )}

          {/* EMAIL */}
          <div className="w-full mb-4">
            <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-2">
              EMAIL
            </label>
            <input
              className="w-full border border-[#cbd5e1] rounded-xl px-4 py-3 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
              type="email"
              name="email"
              placeholder="name@example.com"
              value={formData.email}
              onChange={handleChange}
              required
            />
          </div>

          {/* PASSWORD */}
          <div className="w-full mb-2">
            <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-2">
              PASSWORD
            </label>
            <div className="relative">
              <input
                className="w-full border border-[#cbd5e1] rounded-xl px-4 py-3 pr-11 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                type={showPassword ? "text" : "password"}
                name="password"
                placeholder="••••••••"
                value={formData.password}
                onChange={handleChange}
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-[#0fb5a1] transition-colors focus:outline-none"
              >
                {showPassword ? <Eye size={18} /> : <EyeOff size={18} />}
              </button>
            </div>
          </div>

          {/* Forgot Password Link */}
          <div className="w-full flex justify-end mb-6">
            <button
              type="button"
              onClick={() => router.push(routes.forgotPassword)}
              className="text-xs sm:text-sm font-semibold text-[#0fb5a1] hover:text-[#0d9e8c] hover:underline focus:outline-none"
            >
              Forgot Password?
            </button>
          </div>

          {/* Submit Button */}
          <button
            className="w-full py-3.5 bg-[#0fb5a1] hover:bg-[#0d9e8c] text-white font-semibold rounded-xl text-base shadow-sm transition-all disabled:bg-[#94a3b8] disabled:cursor-not-allowed"
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Logging In..." : "Log In"}
          </button>

          {/* Terms and Privacy Footer */}
          <p className="text-center text-xs text-[#64748b] mt-6 leading-relaxed">
            By logging in, you agree to our{" "}
            <a href="/terms" className="text-[#0fb5a1] font-medium hover:underline">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="/privacy-policy" className="text-[#0fb5a1] font-medium hover:underline">
              Privacy Policy
            </a>
          </p>
        </form>
      </div>
    </div>
  );
}
