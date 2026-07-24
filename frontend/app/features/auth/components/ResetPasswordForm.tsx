"use client";

import React, { useState,Suspense } from 'react';
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import useAxios from "../../../hooks/useAxios";
import { routes } from "../../../services/routes";

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [request, , isSubmitting] = useAxios({ 
    endpoint: "RESET_PASSWORD",
    showSuccessMsg: true,
  });

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("Invalid or expired reset token.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    await request({ 
      data: { 
        token: token,
        new_password: password 
      },
    }, () => {
      router.push(routes.login);
    });
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#e8e8e8] font-sans p-4 overflow-hidden">
      <div className="card-container">
        <div className="circle1" />
        <div className="circle2" />
        <div className="container">
          <form className="log-card" onSubmit={handleSubmit}>
            <p className="heading">Reset Password</p>
            <p className="para">Secure your account with a new password</p>
            
            {error && (
              <p className="text-red-500 text-xs font-bold mt-2 text-center uppercase tracking-wider">{error}</p>
            )}

            <div className="input-group">
              <p className="text">New Password</p>
              <div className="relative mb-2">
                <input 
                  className="input pr-12" 
                  type={showPassword ? "text" : "password"} 
                  placeholder="Enter new password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[#0fb5a1] transition-colors focus:outline-none"
                >
                  {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              </div>
              <p className="text">Confirm Password</p>
              <div className="relative">
                <input 
                  className="input pr-12" 
                  type={showConfirmPassword ? "text" : "password"} 
                  placeholder="Re-enter password" 
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[#0fb5a1] transition-colors focus:outline-none"
                >
                  {showConfirmPassword ?  <Eye size={20} />:<EyeOff size={20} />}
                </button>
              </div>
            </div>

            <button className="btn" type="submit" disabled={isSubmitting || !token}>
              {isSubmitting ? "Updating..." : "Update Password"}
            </button>
            
            {!token && (
              <p className="text-amber-600 text-center text-xs font-bold mt-4 italic">
                A valid reset token is required to proceed.
              </p>
            )}
          </form>
        </div>
      </div>

      <style jsx>{`
        .card-container { width: 100%; max-width: 540px; position: relative; transition: all 0.3s ease; }
        .container { display: flex; height: 100%; width: 100%; align-items: center; justify-content: center; }
        .circle1 { height: 120px; width: 120px; border-radius: 50%; background-color: #0fb5a1; position: absolute; top: -20px; left: -20px; z-index: 0; opacity: 0.9; }
        .circle2 { height: 120px; width: 120px; border-radius: 50%; background-color: #f37e10; position: absolute; right: -20px; bottom: -20px; z-index: 0; opacity: 0.9; }
        .log-card { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif; position: relative; z-index: 10; width: 100%; background: rgba(255, 255, 255, 0.95); border-radius: 28px; display: flex; flex-direction: column; box-shadow: 0 15px 45px rgba(0, 0, 0, 0.08); backdrop-filter: blur(10px); padding: 48px 44px; }
        .heading { font-size: 42px; font-weight: 900; margin-bottom: 4px; color: #0f172a; text-align: center; letter-spacing: -0.02em; }
        .para { font-size: 16px; font-weight: 600; color: #64748b; text-align: center; margin-bottom: 12px; }
        .text { margin-top: 18px; margin-bottom: 8px; font-size: 12px; font-weight: 800; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; margin-left: 2px; }
        .input-group { margin-top: 5px; margin-bottom: 5px; }
        .input { box-sizing: border-box; margin-bottom: 4px; width: 100%; border: 2px solid #f1f5f9; padding: 14px 18px; background-color: #f8fafc; border-radius: 12px; font-weight: 700; color: #0fb5a1; outline: none; font-size: 16px; transition: all 0.2s; }
        .input:hover, .input:focus { border-color: #0fb5a1; background-color: white; box-shadow: 0 2px 12px rgba(15, 181, 161, 0.08); }
        .btn { width: 100%; height: 56px; margin-top: 32px; margin-bottom: 16px; border: none; background-color: #0fb5a1; color: white; font-size: 18px; font-weight: 900; border-radius: 14px; cursor: pointer; transition: all 0.2s; }
        .btn:hover { background-color: #75cfc5ff; transform: translateY(-1px); }
        .btn:disabled { background-color: #94a3b8; cursor: not-allowed; }
      `}</style>
    </div>
  );
}

export default function ResetPasswordForm() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ResetPasswordContent />
    </Suspense>
  );
}
