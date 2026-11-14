"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Script from "next/script";
import { Eye, EyeOff, ArrowLeft, RotateCcw } from "lucide-react";
import { useRegister } from "../hooks/useRegister";
import { useLogin } from "../hooks/useLogin";
import { routes } from "../../../services/routes";
import toast from "react-hot-toast";
import { message } from "antd";
import BrandGlyph from "../../../components/landing/BrandGlyph";

export default function RegisterForm() {
  const router = useRouter();
  const { loginWithGoogle } = useLogin();
  const {
    register,
    sendOtp,
    error,
    setError,
    isSubmitting,
    isSendingOtp,
    showOtpScreen,
    setShowOtpScreen,
    otp,
    setOtp,
    inputRefs,
  } = useRegister();

  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    tenant_name: "",
    email: "",
    password: "",
    confirm_password: "",
  });

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [timeLeft, setTimeLeft] = useState<number>(300);
  const [timerActive, setTimerActive] = useState<boolean>(false);

  const initGoogleBtn = () => {
    if (typeof window !== "undefined" && (window as any).google?.accounts?.id) {
      const clientId =
        process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ||
        "370095760215-9airu0dgt91c4qerggvh66ip693uh8sq.apps.googleusercontent.com";

      (window as any).google.accounts.id.initialize({
        client_id: clientId,
        callback: (response: any) => {
          if (response?.credential) {
            loginWithGoogle(response.credential);
          }
        },
      });

      const googleBtnContainer = document.getElementById("googleRegisterDiv");
      if (googleBtnContainer) {
        googleBtnContainer.innerHTML = "";
        (window as any).google.accounts.id.renderButton(googleBtnContainer, {
          theme: "outline",
          size: "large",
          width: 400,
        });
      }
    }
  };

  useEffect(() => {
    initGoogleBtn();
  }, [showOtpScreen]);

  useEffect(() => {
    let interval: any = null;
    if (showOtpScreen && timerActive && timeLeft > 0) {
      interval = setInterval(() => {
        setTimeLeft((prevTime) => prevTime - 1);
      }, 1000);
    } else if (timeLeft === 0) {
      setTimerActive(false);
      clearInterval(interval);
    }
    return () => clearInterval(interval);
  }, [showOtpScreen, timerActive, timeLeft]);

  useEffect(() => {
    if (showOtpScreen) {
      setTimeLeft(300);
      setTimerActive(true);
      setOtp(new Array(6).fill(""));
    }
  }, [showOtpScreen]);

  useEffect(() => {
    if (error) {
      setOtp(new Array(6).fill(""));
      setTimeout(() => {
        inputRefs.current[0]?.focus();
      }, 50);
    }
  }, [error]);

  const validatePassword = (password: string) => {
    if (!/^(?=.*[a-z])(?=.*[A-Z]).{8,}$/.test(password)) {
      setPasswordError(
        "Password must contain at least 8 characters, 1 uppercase letter, 1 lowercase letter and one number."
      );
    } else {
      setPasswordError("");
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleGetOtpSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (formData.password !== formData.confirm_password) {
      message.error("Passwords do not match");
      return;
    }
    if (passwordError) return;
    setOtp(new Array(6).fill(""));
    sendOtp(formData.email, formData.first_name, formData.tenant_name, formData.password);
  };

  const handleResendOtp = async () => {
    try {
      await sendOtp(formData.email, formData.first_name, formData.tenant_name, formData.password);
      setOtp(new Array(6).fill(""));
      setTimeLeft(300);
      setTimerActive(true);
    } catch (err: any) {
      throw new Error(err);
    }
  };

  const handleOtpChange = (element: HTMLInputElement, index: number) => {
    const value = element.value.replace(/[^0-9]/g, "");
    if (!value) {
      const newOtp = [...otp];
      newOtp[index] = "";
      setOtp(newOtp);
      return;
    }

    const newOtp = [...otp];
    newOtp[index] = value.substring(value.length - 1);
    setOtp(newOtp);

    if (index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleOtpPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pastedText = e.clipboardData.getData("text").replace(/[^0-9]/g, "").substring(0, 6);

    if (pastedText.length > 0) {
      const newOtp = [...otp];
      for (let i = 0; i < 6; i++) {
        if (pastedText[i]) {
          newOtp[i] = pastedText[i];
        }
      }
      setOtp(newOtp);
      const focusIndex = pastedText.length === 6 ? 5 : pastedText.length;
      inputRefs.current[focusIndex]?.focus();
    }
  };

  const handleOtpKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, index: number) => {
    if (e.key === "Backspace") {
      if (!otp[index] && index > 0) {
        const newOtp = [...otp];
        newOtp[index - 1] = "";
        setOtp(newOtp);
        inputRefs.current[index - 1]?.focus();
      } else {
        const newOtp = [...otp];
        newOtp[index] = "";
        setOtp(newOtp);
      }
    }
  };

  const handleFinalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const finalOtpCode = otp.join("");
    if (finalOtpCode.length < 6) {
      setError("Please enter the full 6-digit OTP code");
      return;
    }

    try {
      await register({ ...formData, otp: finalOtpCode });
    } catch (err: any) {
      toast.error(err);
      setOtp(new Array(6).fill(""));
      inputRefs.current[0]?.focus();
    }
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#f3f4f6] font-sans p-4 relative overflow-hidden">
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={initGoogleBtn}
      />

      <div className="w-full max-w-[480px] relative">
        {/* Decorative Background Circles */}
        <div className="w-32 h-32 rounded-full bg-[#0fb5a1] absolute -top-5 -left-5 z-0 opacity-90 pointer-events-none" />
        <div className="w-32 h-32 rounded-full bg-[#f37e10] absolute -bottom-5 -right-5 z-0 opacity-90 pointer-events-none" />

        {!showOtpScreen ? (
          <form
            className="w-full bg-white rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.06)] border border-[#e5e7eb] px-8 py-9 sm:px-10 sm:py-10 flex flex-col items-center relative z-10"
            onSubmit={handleGetOtpSubmit}
          >
            {/* Logo */}
            <div className="mb-6 flex justify-center">
              <BrandGlyph height={42} />
            </div>

            {/* Top Segmented Tab Switcher: Log In / Sign Up */}
            <div className="flex bg-[#f1f5f9] p-1 rounded-2xl mb-6 w-full">
              <button
                type="button"
                onClick={() => router.push(routes.login)}
                className="flex-1 py-2.5 text-sm font-semibold rounded-xl text-[#475569] hover:text-[#0fb5a1] transition-all"
              >
                Log In
              </button>
              <button
                type="button"
                className="flex-1 py-2.5 text-sm font-semibold rounded-xl bg-[#0fb5a1] text-white shadow-sm transition-all"
              >
                Sign Up
              </button>
            </div>

            {/* Google Sign-In / Register Button */}
            <div className="relative w-full mb-4 overflow-hidden rounded-xl">
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

              <div
                id="googleRegisterDiv"
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

            {/* First Name & Last Name */}
            <div className="flex gap-3 w-full mb-3">
              <div className="flex-1">
                <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                  First Name
                </label>
                <input
                  className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                  type="text"
                  name="first_name"
                  placeholder="First"
                  value={formData.first_name}
                  onChange={handleChange}
                  required
                />
              </div>
              <div className="flex-1">
                <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                  Last Name
                </label>
                <input
                  className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                  type="text"
                  name="last_name"
                  placeholder="Last"
                  value={formData.last_name}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>

            {/* Organization Name */}
            <div className="w-full mb-3">
              <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                Organization Name
              </label>
              <input
                className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                type="text"
                name="tenant_name"
                placeholder="e.g. Acme Corp"
                value={formData.tenant_name}
                onChange={handleChange}
                required
              />
            </div>

            {/* Email */}
            <div className="w-full mb-3">
              <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                Email
              </label>
              <input
                className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                type="email"
                name="email"
                placeholder="name@company.com"
                value={formData.email}
                onChange={handleChange}
                required
              />
            </div>

            {/* Password & Confirm */}
            <div className="flex gap-3 w-full mb-4">
              <div className="flex-1">
                <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                  Password
                </label>
                <div className="relative">
                  <input
                    className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 pr-9 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                    type={showPassword ? "text" : "password"}
                    name="password"
                    placeholder="••••••••"
                    value={formData.password}
                    onChange={(e) => {
                      handleChange(e);
                      validatePassword(e.target.value);
                    }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-[#0fb5a1] transition-colors focus:outline-none"
                  >
                    {showPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                  </button>
                </div>
                {passwordError && (
                  <p className="mt-1 text-[11px] font-medium text-red-500 leading-tight">{passwordError}</p>
                )}
              </div>

              <div className="flex-1">
                <label className="block text-xs font-bold text-[#0f172a] uppercase tracking-wider mb-1.5">
                  Confirm
                </label>
                <div className="relative">
                  <input
                    className="w-full border border-[#cbd5e1] rounded-xl px-3.5 py-2.5 pr-9 text-sm text-[#0f172a] placeholder-[#94a3b8] outline-none transition-all focus:border-[#0fb5a1] focus:ring-2 focus:ring-[#0fb5a1]/15"
                    type={showConfirmPassword ? "text" : "password"}
                    name="confirm_password"
                    placeholder="••••••••"
                    value={formData.confirm_password}
                    onChange={handleChange}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[#94a3b8] hover:text-[#0fb5a1] transition-colors focus:outline-none"
                  >
                    {showConfirmPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                  </button>
                </div>
              </div>
            </div>

            {/* Submit Button */}
            <button
              className="w-full py-3.5 bg-[#0fb5a1] hover:bg-[#0d9e8c] text-white font-semibold rounded-xl text-base shadow-sm transition-all disabled:bg-[#94a3b8] disabled:cursor-not-allowed"
              type="submit"
              disabled={isSendingOtp}
            >
              {isSendingOtp ? "Sending OTP..." : "Get OTP"}
            </button>

            {/* Terms and Privacy Footer */}
            <p className="text-center text-xs text-[#64748b] mt-5 leading-relaxed">
              By registering, you agree to our{" "}
              <a href="/terms" className="text-[#0fb5a1] font-medium hover:underline">
                Terms of Service
              </a>{" "}
              and{" "}
              <a href="/privacy-policy" className="text-[#0fb5a1] font-medium hover:underline">
                Privacy Policy
              </a>
            </p>
          </form>
        ) : (
          <form
            className="w-full bg-white rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.06)] border border-[#e5e7eb] px-8 py-9 sm:px-10 sm:py-10 flex flex-col items-center relative z-10"
            onSubmit={handleFinalSubmit}
          >
            <button
              type="button"
              onClick={() => setShowOtpScreen(false)}
              className="flex items-center gap-1.5 text-xs font-bold text-[#0fb5a1] mb-5 hover:underline focus:outline-none self-start"
            >
              <ArrowLeft size={16} /> Back to Details
            </button>

            <h2 className="text-2xl font-bold text-[#0f172a] mb-1 text-center">Verify Identity</h2>
            <p className="text-sm text-[#64748b] text-center mb-6">
              Enter the 6-digit code sent to <span className="font-semibold text-[#0f172a]">{formData.email}</span>
            </p>

            {error && (
              <p className="text-red-500 text-xs font-semibold mb-3 text-center w-full">{error}</p>
            )}

            <div className="flex justify-between gap-2.5 my-3 w-full">
              {otp.map((data, index) => (
                <input
                  key={index}
                  type="text"
                  maxLength={1}
                  className="flex-1 min-w-0 max-w-[54px] h-14 border-2 border-[#cbd5e1] bg-[#f8fafc] rounded-xl text-xl font-bold text-[#0fb5a1] text-center outline-none transition-all focus:border-[#0fb5a1] focus:bg-white focus:ring-2 focus:ring-[#0fb5a1]/15 disabled:bg-[#e2e8f0] disabled:cursor-not-allowed"
                  value={data}
                  disabled={timeLeft === 0}
                  ref={(el) => {
                    if (el) inputRefs.current[index] = el;
                  }}
                  onChange={(e) => handleOtpChange(e.target, index)}
                  onKeyDown={(e) => handleOtpKeyDown(e, index)}
                  onPaste={handleOtpPaste}
                />
              ))}
            </div>

            <div className="flex flex-col items-center justify-center my-3">
              {timeLeft > 0 ? (
                <p className="text-xs font-semibold text-[#64748b]">
                  Time remaining: <span className="text-red-500 font-bold">{formatTime(timeLeft)}</span>
                </p>
              ) : (
                <div className="flex flex-col items-center gap-1.5 mt-1">
                  <p className="text-xs text-red-500 font-bold">OTP code expired!</p>
                  <button
                    type="button"
                    onClick={handleResendOtp}
                    className="flex items-center gap-1 text-sm font-bold text-[#0fb5a1] hover:underline focus:outline-none"
                    disabled={isSendingOtp}
                  >
                    <RotateCcw size={14} /> {isSendingOtp ? "Sending..." : "Resend OTP"}
                  </button>
                </div>
              )}
            </div>

            <button
              className="w-full py-3.5 bg-[#0fb5a1] hover:bg-[#0d9e8c] text-white font-semibold rounded-xl text-base shadow-sm transition-all mt-4 disabled:bg-[#94a3b8] disabled:cursor-not-allowed"
              type="submit"
              disabled={isSubmitting || timeLeft === 0}
            >
              {isSubmitting ? "Verifying & Registering..." : "Verify & Complete Registration"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
