"use client";

import React, { useState } from 'react';
import { useRouter } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "../hooks/useLogin";
import { routes } from "../../../services/routes";

export default function LoginForm() {
  const router = useRouter();
  const { login, error, isSubmitting } = useLogin();
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    login(formData);
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#e8e8e8] font-sans p-4 overflow-hidden">
      <div className="card-container">
        <div className="circle1" />
        <div className="circle2" />
        <div className="container">
          <form className="log-card" onSubmit={handleSubmit}>
            <p className="heading">Welcome Back</p>
            <p className="para">We are glad to have you again</p>
            
            {error && (
              <p className="text-red-500 text-xs font-bold mt-2 text-center">{error}</p>
            )}

            <div className="input-group">
              <p className="text">Username / Email</p>
              <input 
                className="input" 
                type="text" 
                name="email"
                placeholder="For Ex: Jayakrishna007" 
                value={formData.email}
                onChange={handleChange}
                required
              />
              <p className="text">Password</p>
              <div className="relative group">
                <input 
                  className="input pr-12" 
                  type={showPassword ? "text" : "password"} 
                  name="password"
                  placeholder="Enter Password" 
                  value={formData.password}
                  onChange={handleChange}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[#0fb5a1] transition-colors focus:outline-none"
                >
                  {showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
                </button>
              </div>
            </div>

            <div className="password-group">
              <div className="checkbox-group">
                <input type="checkbox" id="remember" className="mr-2 h-4 w-4" />
                <label className="label" htmlFor="remember">Remember Me</label>
              </div>
              <a 
                onClick={() => router.push(routes.forgotPassword)} 
                className="forget-password cursor-pointer"
              >
                Forget Password
              </a>
            </div>

            <button className="btn" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing In..." : "Sign In"}
            </button>
            
            <p className="no-account">
              {`Don't Have an Account ?`}
              <a 
                className="link cursor-pointer ml-1" 
                onClick={() => router.push(routes.register)}
              >
                Sign Up
              </a>
            </p>
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
        .password-group { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; padding: 0 2px; }
        .checkbox-group { color: #1e293b; font-size: 14px; font-weight: 700; display: flex; align-items: center; }
        .forget-password { font-size: 14px; font-weight: 700; color: #0fb5a1; text-decoration: none; }
        .forget-password:hover { color: #f37e10; }
        .btn { width: 100%; height: 56px; margin-top: 32px; margin-bottom: 16px; border: none; background-color: #0fb5a1; color: white; font-size: 18px; font-weight: 900; border-radius: 14px; cursor: pointer; transition: all 0.2s; }
        .btn:hover { background-color: #75cfc5ff; transform: translateY(-1px); }
        .btn:disabled { background-color: #94a3b8; cursor: not-allowed; }
        .no-account { font-size: 15px; font-weight: 600; color: #64748b; text-align: center; }
        .link { font-weight: 900; color: #0fb5a1; text-decoration: underline; text-underline-offset: 4px; }
        .link:hover { color: #f37e10; }
      `}</style>
    </div>
  );
}