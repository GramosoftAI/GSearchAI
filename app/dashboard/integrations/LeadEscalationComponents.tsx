"use client";

import React, { useState } from "react";
import {
  UserOutlined,
  MailOutlined,
  PhoneOutlined,
  ArrowRightOutlined,
  CustomerServiceOutlined,
  FileTextOutlined
} from "@ant-design/icons";

interface LeadCaptureFormProps {
  fields: string;
  themeColor: string;
  isDark: boolean;
  onSubmit: (data: Record<string, string>) => void;
}

export function LeadCaptureForm({ fields, themeColor, isDark, onSubmit }: LeadCaptureFormProps) {
  const parsedFields = fields
    .split(",")
    .map((f) => f.trim().toLowerCase())
    .filter(Boolean);

  const [formValues, setFormValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    parsedFields.forEach((field) => {
      initial[field] = "";
    });
    return initial;
  });

  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleInputChange = (field: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [field]: value }));
    if (errors[field]) {
      setErrors((prev) => ({ ...prev, [field]: "" }));
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    parsedFields.forEach((field) => {
      const val = formValues[field]?.trim();
      if (!val) {
        newErrors[field] = `${field.charAt(0).toUpperCase() + field.slice(1)} is required`;
      } else if (field === "email" && !/\S+@\S+\.\S+/.test(val)) {
        newErrors[field] = "Please enter a valid email address";
      }
    });

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    onSubmit(formValues);
  };

  const getFieldIcon = (field: string) => {
    if (field.includes("email")) return <MailOutlined className="text-slate-400" />;
    if (field.includes("phone") || field.includes("mobile") || field.includes("contact")) {
      return <PhoneOutlined className="text-slate-400" />;
    }
    if (field.includes("name")) return <UserOutlined className="text-slate-400" />;
    return <FileTextOutlined className="text-slate-400" />;
  };

  return (
    <div
      style={{
        backgroundColor: isDark ? "#090d16" : "#f8fafc",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        padding: "20px 24px",
      }}
      className="animate-in fade-in slide-in-from-bottom duration-300"
    >
      <div className="text-center mb-5">
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center mx-auto mb-2.5 shadow-sm"
          style={{ backgroundColor: `${themeColor}20`, color: themeColor }}
        >
          <UserOutlined className="text-lg" />
        </div>
        <h4
          style={{ color: isDark ? "#ffffff" : "#1e293b" }}
          className="m-0 font-extrabold text-sm tracking-tight"
        >
          Introduce Yourself
        </h4>
        <p
          style={{ color: isDark ? "#94a3b8" : "#64748b" }}
          className="m-0 text-[10px] leading-relaxed mt-1"
        >
          Please fill out the details below to start chatting with our agent.
        </p>
      </div>

      <form onSubmit={handleFormSubmit} className="space-y-3.5">
        {parsedFields.map((field) => {
          const hasError = !!errors[field];
          return (
            <div key={field} className="flex flex-col gap-1 text-left">
              <label
                style={{ color: isDark ? "#cbd5e1" : "#475569" }}
                className="text-[10px] font-bold uppercase tracking-wider pl-0.5"
              >
                {field.charAt(0).toUpperCase() + field.slice(1)}
              </label>
              <div
                style={{
                  backgroundColor: isDark ? "#0f172a" : "#ffffff",
                  borderColor: hasError ? "#ef4444" : isDark ? "#1e293b" : "#cbd5e1",
                }}
                className="flex items-center border rounded-xl px-3 py-2 gap-2 shadow-xs transition-all"
              >
                {getFieldIcon(field)}
                <input
                  type={field === "email" ? "email" : "text"}
                  value={formValues[field] || ""}
                  onChange={(e) => handleInputChange(field, e.target.value)}
                  placeholder={`Enter your ${field}`}
                  style={{
                    backgroundColor: "transparent",
                    color: isDark ? "#ffffff" : "#1e293b",
                    border: "none",
                    outline: "none",
                    flex: 1,
                    fontSize: "11px",
                  }}
                />
              </div>
              {hasError && (
                <span className="text-[9px] text-red-500 font-medium pl-1">
                  {errors[field]}
                </span>
              )}
            </div>
          );
        })}

        <button
          type="submit"
          style={{
            background: themeColor,
            color: "#ffffff",
          }}
          className="w-full mt-4 h-9 rounded-xl flex items-center justify-center gap-1.5 text-xs font-bold border-none cursor-pointer shadow-md hover:opacity-95 transition-all duration-200"
        >
          Start Chat
          <ArrowRightOutlined />
        </button>
      </form>
    </div>
  );
}

interface EscalationHeaderLinkProps {
  escalationLink: string;
  themeColor: string;
  isDark: boolean;
}

export function EscalationHeaderLink({ escalationLink, themeColor, isDark }: EscalationHeaderLinkProps) {
  return (
    <a
      href={escalationLink}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        backgroundColor: `${themeColor}20`,
        color: themeColor,
      }}
      className="px-2.5 py-1 rounded-lg text-[10px] font-bold flex items-center gap-1 hover:scale-105 transition-all border border-transparent"
      title="Escalate to human support agent"
    >
      <CustomerServiceOutlined />
      <span>Talk to Human</span>
    </a>
  );
}

interface EscalationSystemMessageProps {
  escalationLink: string;
  themeColor: string;
  isDark: boolean;
}

export function EscalationSystemMessage({ escalationLink, themeColor, isDark }: EscalationSystemMessageProps) {
  return (
    <div
      style={{
        backgroundColor: isDark ? "#0f172a" : "#ffffff",
        borderColor: isDark ? "#1e293b" : "#e2e8f0",
      }}
      className="p-3 rounded-2xl border flex flex-col gap-2.5 shadow-sm text-left animate-in fade-in slide-in-from-bottom duration-300 w-[95%] mx-auto"
    >
      <div className="flex items-start gap-2">
        <div
          className="w-6 h-6 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{ backgroundColor: `${themeColor}20`, color: themeColor }}
        >
          <CustomerServiceOutlined className="text-xs" />
        </div>
        <div className="flex flex-col gap-0.5">
          <span
            style={{ color: isDark ? "#ffffff" : "#1e293b" }}
            className="text-[10px] font-extrabold"
          >
            Human Escalation Available
          </span>
          <span
            style={{ color: isDark ? "#94a3b8" : "#64748b" }}
            className="text-[9px] leading-relaxed"
          >
            If our AI agent couldn't answer your question, connect with our human support representatives.
          </span>
        </div>
      </div>
      <a
        href={escalationLink}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          backgroundColor: themeColor,
          color: "#ffffff",
        }}
        className="h-7 w-full rounded-lg text-[9px] font-extrabold flex items-center justify-center gap-1 border-none cursor-pointer text-center hover:opacity-90 transition-all select-none no-underline"
      >
        <span>Connect with Human Agent</span>
        <ArrowRightOutlined />
      </a>
    </div>
  );
}
