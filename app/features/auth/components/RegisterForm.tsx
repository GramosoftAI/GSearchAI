"use client";

import React, { useState,useEffect } from 'react';
import { useRouter } from "next/navigation";
import { Eye, EyeOff, ArrowLeft, RotateCcw } from "lucide-react";
import { useRegister } from "../hooks/useRegister";
import { routes } from "../../../services/routes";
import toast from 'react-hot-toast';
import { message } from 'antd';


export default function RegisterForm() {
  const router = useRouter();
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
    inputRefs
  } = useRegister();

  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    tenant_name: "",
    email: "",
    password: "",
    confirm_password: ""
  });

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [timeLeft, setTimeLeft] = useState<number>(300);
  const [timerActive, setTimerActive] = useState<boolean>(false);

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
        "Password must contain at least 8 characters, 1 uppercase letter,1 lowercase letter and one number."
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
    sendOtp(formData.email,formData.first_name,formData.tenant_name,formData.password)
  };


  const handleResendOtp = async () => {
    try {
      await sendOtp(formData.email ,formData.first_name,formData.tenant_name,formData.password);
      
      setOtp(new Array(6).fill(""));
      setTimeLeft(300);
      setTimerActive(true);
    } catch (err : any) {
      
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

  const handleFinalSubmit = async(e: React.FormEvent) => {
    e.preventDefault();
    const finalOtpCode = otp.join("");
    if (finalOtpCode.length < 6) {
      setError("Please enter the full 6-digit OTP code");
      return;
    }
   
    try {
      await register({ ...formData, otp: finalOtpCode });
    } catch (err :any) {
      toast.error(err);
      
      setOtp(new Array(6).fill(""));
      inputRefs.current[0]?.focus();
    }
  };

  
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-[#e8e8e8] font-sans p-4 overflow-hidden">
      <div className="card-container">
        <div className="circle1" />
        <div className="circle2" />
        <div className="container">
          
          {!showOtpScreen ? (
            
            <form className="log-card" onSubmit={handleGetOtpSubmit}>
              <p className="heading">Create Account</p>
              <p className="para">Join the future of knowledge graphs</p>
              
              {error && (
                <p className="text-red-500 text-xs font-bold mt-1 text-center">{error}</p>
              )}

              <div className="input-group">
                <div className="flex gap-4 mb-1">
                  <div className="flex-1">
                    <p className="text">First Name</p>
                    <input className="input" type="text" name="first_name" placeholder="First" value={formData.first_name} onChange={handleChange} required />
                  </div>
                  <div className="flex-1">
                    <p className="text">Last Name</p>
                    <input className="input" type="text" name="last_name" placeholder="Last" value={formData.last_name} onChange={handleChange} required />
                  </div>
                </div>

                <p className="text">Organization Name</p>
                <input className="input" type="text" name="tenant_name" placeholder="e.g. Acme Corp" value={formData.tenant_name} onChange={handleChange} required />
                
                <p className="text">Email</p>
                <input className="input" type="email" name="email" placeholder="name@company.com" value={formData.email} onChange={handleChange} required />
                
                <div className="flex gap-4">
                  <div className="flex-1">
                    <p className="text">Password</p>
                    <div className="relative">
                      <input 
                        className="input pr-10" 
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
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[#0fb5a1] transition-colors focus:outline-none"
                      >
                        {showPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                      </button>
                    </div>
                    {passwordError && (
                      <p className="mt-1 text-xs font-semibold text-red-500">{passwordError}</p>
                    )}
                  </div>
                  <div className="flex-1">
                    <p className="text">Confirm</p>
                    <div className="relative">
                      <input 
                        className="input pr-10" 
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
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[#0fb5a1] transition-colors focus:outline-none"
                      >
                        {showConfirmPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <button className="btn" type="submit" disabled={isSendingOtp}>
                {isSendingOtp ? "Sending OTP..." : "Get OTP"}
              </button>
              
              <p className="no-account">
                Already have an account?
                <a className="link cursor-pointer ml-1" onClick={() => router.push(routes.login)}>
                  Sign In
                </a>
              </p>
            </form>
          ) : (
            
            <form className="log-card" onSubmit={handleFinalSubmit}>
              <button 
                type="button" 
                onClick={() => setShowOtpScreen(false)} 
                className="flex items-center gap-1 text-xs font-bold text-[#0fb5a1] mb-4 hover:underline focus:outline-none self-start"
              >
                <ArrowLeft size={14} /> Back to Details
              </button>

              <p className="heading">Verify Identity</p>
              <p className="para">Enter the 6-digit code sent to {formData.email}</p>

              {error && (
                <p className="text-red-500 text-xs font-bold mt-1 text-center">{error}</p>
              )}

              <div className="otp-container">
                {otp.map((data, index) => (
                  <input
                    key={index}
                    type="text"
                    maxLength={1}
                    className="otp-box"
                    value={data}
                    disabled={timeLeft === 0}
                    ref={(el) => { if(el) inputRefs.current[index] = el; }}
                    onChange={(e) => handleOtpChange(e.target, index)}
                    onKeyDown={(e) => handleOtpKeyDown(e, index)}
                    onPaste={handleOtpPaste}
                  />
                ))}
              </div>

              <div className="flex flex-col items-center justify-center my-2">
                {timeLeft > 0 ? (
                  <p className="timer-text">
                    Time remaining: <span className="text-red-500 font-bold">{formatTime(timeLeft)}</span>
                  </p>
                ) : (
                  <div className="flex flex-col items-center gap-2 mt-1">
                    <p className="text-xs text-red-500 font-bold">OTP code expired!</p>
                    <button 
                      type="button" 
                      onClick={handleResendOtp}
                      className="flex items-center gap-1 text-sm font-black text-[#f37e10] hover:underline focus:outline-none"
                      disabled={isSendingOtp}
                    >
                      <RotateCcw size={14} /> {isSendingOtp ? "Sending..." : "Resend OTP"}
                    </button>
                  </div>
                )}
              </div>

              <button className="btn mt-4" type="submit" disabled={isSubmitting || timeLeft === 0}>
                {isSubmitting ? "Verifying & Registering..." : "Verify & Complete Registration"}
              </button>
            </form>
          )}

        </div>
      </div>

      <style jsx>{`
        .card-container { width: 100%; max-width: 540px; position: relative; transition: all 0.3s ease; }
        .container { display: flex; height: 100%; width: 100%; align-items: center; justify-content: center; }
        .circle1 { height: 120px; width: 120px; border-radius: 50%; background-color: #0fb5a1; position: absolute; top: -20px; left: -20px; z-index: 0; opacity: 0.9; }
        .circle2 { height: 120px; width: 120px; border-radius: 50%; background-color: #f37e10; position: absolute; right: -20px; bottom: -20px; z-index: 0; opacity: 0.9; }
        .log-card { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif; position: relative; z-index: 10; width: 100%; background: rgba(255, 255, 255, 0.95); border-radius: 28px; display: flex; flex-direction: column; box-shadow: 0 15px 45px rgba(0, 0, 0, 0.08); backdrop-filter: blur(10px); padding: 40px 44px; }
        .heading { font-size: 38px; font-weight: 900; margin-bottom: 2px; color: #0f172a; text-align: center; letter-spacing: -0.02em; }
        .para { font-size: 14px; font-weight: 600; color: #64748b; text-align: center; margin-bottom: 8px; }
        .text { margin-top: 12px; margin-bottom: 4px; font-size: 11px; font-weight: 800; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.08em; margin-left: 2px; }
        .input-group { margin-top: 5px; margin-bottom: 8px; }
        .input { box-sizing: border-box; margin-bottom: 2px; width: 100%; border: 2px solid #f1f5f9; padding: 12px 16px; background-color: #f8fafc; border-radius: 12px; font-weight: 700; color: #0fb5a1; outline: none; font-size: 15px; transition: all 0.2s; }
        .input:hover, .input:focus { border-color: #0fb5a1; background-color: white; box-shadow: 0 2px 10px rgba(15, 181, 161, 0.06); }
        
        .otp-container { display: flex; justify-content: space-between; gap: 8px; margin: 20px 0 10px 0; width: 100%; }
        .otp-box { flex: 1; min-width: 0; max-width: 52px; height: 55px; border: 2px solid #b8b8b8; background-color: #f8fafc; border-radius: 12px; font-size: 22px; font-weight: 800; color: #0fb5a1; text-align: center; outline: none; transition: all 0.2s; }
        .otp-box:hover, .otp-box:focus { border-color: #0fb5a1; background-color: white; box-shadow: 0 2px 10px rgba(15, 181, 161, 0.06); }
        .otp-box:disabled { background-color: #e2e8f0; border-color: #cbd5e1; color: #94a3b8; cursor: not-allowed; }
        
        .timer-text { font-size: 13px; font-weight: 700; color: #64748b; }
        .btn { width: 100%; margin-top: 16px; margin-bottom: 12px; padding: 14px; border: none; background-color: #0fb5a1; color: white; font-size: 17px; font-weight: 900; border-radius: 14px; cursor: pointer; transition: all 0.2s; }
        .btn:hover { background-color: #75cfc5ff; transform: translateY(-1px); }
        .btn:disabled { background-color: #94a3b8; cursor: not-allowed; transform: none; }
        .no-account { font-size: 14px; font-weight: 600; color: #64748b; text-align: center; }
        .link { font-weight: 900; color: #0fb5a1; text-decoration: underline; }
        .link:hover { color: #f37e10; }

        @media (max-width: 480px) {
          .log-card { padding: 30px 20px; }
          .heading { font-size: 30px; }
          .otp-box { height: 46px; font-size: 18px; border-radius: 10px; }
          .otp-container { gap: 6px; }
        }
      `}</style>
    </div>
  );
}