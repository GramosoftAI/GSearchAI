"use client";

import React, { useState } from "react";
import Link from "next/link";
import BrandGlyph from "@/app/components/landing/BrandGlyph";
import { 
  FaSlack, 
  FaCheck, 
  FaCopy, 
  FaArrowRight, 
  FaComments, 
  FaMagnifyingGlass, 
  FaGear, 
  FaCircleCheck,
  FaShieldHalved,
  FaArrowUpRightFromSquare 
} from "react-icons/fa6";

export default function SlackInstallationSuccessPage() {
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <div style={{ background: "#ffffff", minHeight: "100vh", color: "#14161f" }}>
      {/* Header */}
      <header style={{ borderBottom: "1px solid #eef2f6", background: "#ffffff", padding: "16px 24px" }}>
        <div style={{ maxWidth: "1140px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Link href="/" style={{ display: "flex", alignItems: "center" }}>
            <BrandGlyph height={34} />
          </Link>
          <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
            <Link href="/dashboard" style={{ fontSize: "14px", fontWeight: 600, color: "#414856" }}>
              Go to Dashboard
            </Link>
            <Link 
              href="/privacy-policy" 
              style={{ fontSize: "14px", fontWeight: 600, color: "#414856" }}
            >
              Privacy Policy
            </Link>
          </div>
        </div>
      </header>

      {/* Main Success Container */}
      <main style={{ maxWidth: "860px", margin: "0 auto", padding: "56px 24px 80px" }}>
        {/* Celebration Header Card */}
        <div 
          style={{ 
            background: "linear-gradient(135deg, rgba(15, 181, 161, 0.08) 0%, rgba(74, 21, 75, 0.06) 100%)", 
            border: "1px solid #d1fae5", 
            borderRadius: "20px", 
            padding: "44px 32px", 
            textAlign: "center",
            marginBottom: "36px"
          }}
        >
          <div 
            style={{ 
              width: "72px", 
              height: "72px", 
              borderRadius: "50%", 
              background: "#10b981", 
              color: "#ffffff", 
              display: "flex", 
              alignItems: "center", 
              justifyContent: "center", 
              fontSize: "36px", 
              margin: "0 auto 20px",
              boxShadow: "0 8px 24px rgba(16, 185, 129, 0.35)"
            }}
          >
            <FaCheck />
          </div>

          <div 
            style={{ 
              display: "inline-flex", 
              alignItems: "center", 
              gap: "6px", 
              background: "#dcfce7", 
              color: "#166534", 
              padding: "4px 14px", 
              borderRadius: "999px", 
              fontSize: "13px", 
              fontWeight: 700, 
              marginBottom: "16px" 
            }}
          >
            <FaCircleCheck />
            <span>Installation Complete</span>
          </div>

          <h1 style={{ fontSize: "clamp(28px, 4vw, 38px)", fontWeight: 800, color: "#14161f", marginBottom: "12px", letterSpacing: "-0.02em" }}>
            GSearchAI is successfully connected to Slack!
          </h1>
          <p style={{ fontSize: "16.5px", color: "#475569", maxWidth: "600px", margin: "0 auto 28px", lineHeight: 1.6 }}>
            Your Slack workspace is now linked to GSearchAI. Follow the quick steps below to start searching across company documents directly from Slack channels.
          </p>

          <div style={{ display: "flex", justifyContent: "center", gap: "14px", flexWrap: "wrap" }}>
            <a 
              href="slack://open" 
              style={{ 
                display: "inline-flex", 
                alignItems: "center", 
                gap: "8px", 
                background: "#4A154B", 
                color: "#ffffff", 
                padding: "12px 24px", 
                borderRadius: "10px", 
                fontWeight: 700, 
                fontSize: "15px",
                boxShadow: "0 4px 12px rgba(74, 21, 75, 0.25)" 
              }}
            >
              <FaSlack />
              <span>Launch Slack Now</span>
            </a>
            <Link 
              href="/dashboard/integrations" 
              style={{ 
                display: "inline-flex", 
                alignItems: "center", 
                gap: "8px", 
                background: "#ffffff", 
                color: "#14161f", 
                padding: "12px 24px", 
                borderRadius: "10px", 
                fontWeight: 700, 
                fontSize: "15px", 
                border: "1px solid #cbd5e1" 
              }}
            >
              <FaGear />
              <span>Configure Connectors</span>
            </Link>
          </div>
        </div>

        {/* Clear Next Steps */}
        <div style={{ marginBottom: "40px" }}>
          <h2 style={{ fontSize: "22px", fontWeight: 800, color: "#14161f", marginBottom: "20px" }}>
            3 Simple Next Steps to Get Started:
          </h2>

          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* Step 1 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "12px", padding: "20px 24px", display: "flex", gap: "16px", alignItems: "flex-start" }}>
              <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "#4A154B", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: "14px", flexShrink: 0 }}>
                1
              </div>
              <div style={{ flex: 1 }}>
                <h3 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                  Invite GSearchAI to your team channels
                </h3>
                <p style={{ fontSize: "14px", color: "#64748b", margin: "0 0 10px", lineHeight: 1.5 }}>
                  Go to any channel in Slack where you want the assistant active and type:
                </p>
                <div style={{ display: "inline-flex", alignItems: "center", gap: "10px", background: "#ffffff", border: "1px solid #cbd5e1", padding: "6px 12px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px" }}>
                  <span>/invite @GSearchAI</span>
                  <button 
                    onClick={() => copyToClipboard("/invite @GSearchAI", "invite")}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                  >
                    {copied === "invite" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                  </button>
                </div>
              </div>
            </div>

            {/* Step 2 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "12px", padding: "20px 24px", display: "flex", gap: "16px", alignItems: "flex-start" }}>
              <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "#4A154B", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: "14px", flexShrink: 0 }}>
                2
              </div>
              <div style={{ flex: 1 }}>
                <h3 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                  Try your first test question in Slack
                </h3>
                <p style={{ fontSize: "14px", color: "#64748b", margin: "0 0 10px", lineHeight: 1.5 }}>
                  Mention the bot or run a slash query to test retrieval from your connected documents:
                </p>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", background: "#ffffff", border: "1px solid #cbd5e1", padding: "6px 12px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px" }}>
                    <span>@GSearchAI What is our refund policy?</span>
                    <button 
                      onClick={() => copyToClipboard("@GSearchAI What is our refund policy?", "q1")}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                    >
                      {copied === "q1" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                    </button>
                  </div>
                  <div style={{ display: "inline-flex", alignItems: "center", gap: "8px", background: "#ffffff", border: "1px solid #cbd5e1", padding: "6px 12px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px" }}>
                    <span>/gsearch company security standards</span>
                    <button 
                      onClick={() => copyToClipboard("/gsearch company security standards", "q2")}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                    >
                      {copied === "q2" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Step 3 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "12px", padding: "20px 24px", display: "flex", gap: "16px", alignItems: "flex-start" }}>
              <div style={{ width: "32px", height: "32px", borderRadius: "50%", background: "#4A154B", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: "14px", flexShrink: 0 }}>
                3
              </div>
              <div style={{ flex: 1 }}>
                <h3 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                  Index your Google Drive, Notion, &amp; Confluence
                </h3>
                <p style={{ fontSize: "14px", color: "#64748b", margin: "0 0 10px", lineHeight: 1.5 }}>
                  Ensure your documents are fully indexed so GSearchAI can provide rich, accurate answers with citations.
                </p>
                <Link 
                  href="/dashboard/integrations" 
                  style={{ fontSize: "13.5px", color: "#0a8576", fontWeight: 700, display: "inline-flex", alignItems: "center", gap: "6px" }}
                >
                  <span>Open Knowledge Connectors in Dashboard</span>
                  <FaArrowRight style={{ fontSize: "12px" }} />
                </Link>
              </div>
            </div>
          </div>
        </div>

        {/* Support & Privacy footer notice */}
        <div 
          style={{ 
            background: "#ffffff", 
            border: "1px solid #e2e8f0", 
            borderRadius: "12px", 
            padding: "20px 24px", 
            display: "flex", 
            justifyContent: "space-between", 
            alignItems: "center",
            flexWrap: "wrap",
            gap: "16px"
          }}
        >
          <div>
            <div style={{ fontWeight: 700, fontSize: "14.5px", color: "#1e293b", marginBottom: "4px" }}>
              Need help or have questions?
            </div>
            <div style={{ fontSize: "13.5px", color: "#64748b" }}>
              Contact our team at <a href="mailto:gsearchai@gmail.com" style={{ color: "#0a8576", fontWeight: 600 }}>gsearchai@gmail.com</a>
            </div>
          </div>
          <div style={{ display: "flex", gap: "16px", fontSize: "13.5px" }}>
            <Link href="/slack" style={{ color: "#0a8576", fontWeight: 600 }}>
              Slack Landing Page
            </Link>
            <Link href="/privacy-policy" style={{ color: "#0a8576", fontWeight: 600 }}>
              Privacy Policy
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
