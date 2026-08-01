"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { setCookie } from "../../../config/cookies";
import { AUTH_COOKIE_KEY } from "../../../config/config";
import { routes } from "../../../services/routes";
import { useStore } from "../../../hooks/useStore";
import { useRegisterApi } from "../api";
import { RegisterFormValues } from "../types";
import toast from "react-hot-toast";

interface ExtendedRegisterValues extends RegisterFormValues {
  otp: string;
}

export function useRegister() {
  const router = useRouter();

  const setUserId = useStore((s) => s.setUserId);
  const [otp, setOtp] = useState<string[]>(new Array(6).fill(""));
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showOtpScreen, setShowOtpScreen] = useState(false);
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const inputRefs = useRef<HTMLInputElement[]>([]);
  const [request] = useRegisterApi(setOtp, inputRefs);


  async function sendOtp(email: string, firstname: string, tentantName: string, password: string, onErrorCallback?: () => void,) {
    setError(null);
    setIsSendingOtp(true);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/auth/send-registration-otp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email: email.trim(), first_name: firstname, tenant_name: tentantName, password: password }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data?.message || "Failed to send OTP code...............");


      }
      else {
        toast.success(data?.meta?.message)
      }

      setShowOtpScreen(true);
    } catch (err: any) {
      if (onErrorCallback) onErrorCallback();
      setError(err?.message || "Something went wrong while sending OTP.");
      toast.error(err?.message || "Something went wrong while sending OTP.")
    } finally {
      setIsSendingOtp(false);
    }
  }
  async function register(values: ExtendedRegisterValues) {
    setError(null);
    setIsSubmitting(true);

    try {
      await request(
        {
          data: {
            first_name: values.first_name.trim(),
            last_name: values.last_name.trim(),
            email: values.email.trim(),
            password: values.password,
            confirm_password: values.confirm_password,
            tenant_name: values.tenant_name.trim(),
            otp: values.otp,
          },
        },
        (res: any) => {
          console.log("fsahhfggggggggggggggggggggggssssssssssssssssssss", res)
          if (res?.status === 400) {
            console.log("lllllllllllllllllllll")
            setOtp(new Array(6).fill(""));
          }
          const responseData = res?.data;
          const user = responseData?.user;
          const userId = user?.id;

          if (userId) {
            setUserId(userId);
            localStorage.setItem("userId", userId);
          }

          if (user) {
            localStorage.setItem("userName", `${user.first_name} ${user.last_name}`);
            router.push(routes.dashboard || "/dashboard");
          }

          const token = responseData?.tokens?.access_token ?? "";
          setCookie(AUTH_COOKIE_KEY, token);
          if (typeof window !== "undefined" && token) {
            localStorage.setItem("AUTH_TOKEN", token);
            localStorage.setItem("token", token);
          }
        }
      );
    } catch (err: unknown) {
      let msg = "Registration & OTP verification failed";
      if (typeof err === "object" && err && "data" in err) {
        const d = (err as { data?: unknown }).data;
        if (d && typeof d === "object" && "message" in d) {
          const m = (d as { message?: unknown }).message;
          if (typeof m === "string") msg = m;
        }
      }
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  return {
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
  };
}