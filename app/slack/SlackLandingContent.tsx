"use client";

import React, { useState } from "react";
import Link from "next/link";
import BrandGlyph from "@/app/components/landing/BrandGlyph";
import { 
  FaSlack, 
  FaGoogleDrive, 
  FaJira, 
  FaGithub, 
  FaArrowRight, 
  FaCheck, 
  FaCopy, 
  FaShieldHalved, 
  FaLock, 
  FaBolt, 
  FaComments, 
  FaMagnifyingGlass, 
  FaArrowUpRightFromSquare, 
  FaCircleQuestion,
  FaFileLines,
  FaCircleCheck,
  FaRegLightbulb
} from "react-icons/fa6";
import { SiNotion, SiConfluence } from "react-icons/si";

export default function SlackLandingContent() {
  const [activeTab, setActiveTab] = useState<"channel" | "slash" | "thread">("channel");
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCommand(id);
    setTimeout(() => setCopiedCommand(null), 2000);
  };

  // Slack Install destination URL (can be customized via NEXT_PUBLIC_SLACK_INSTALL_URL or default to dashboard integration)
  const slackInstallUrl =
    process.env.NEXT_PUBLIC_SLACK_INSTALL_URL ||
    "/dashboard/integrations";

  return (
    <div className="slack-landing-page" style={{ background: "#ffffff", color: "#14161f", minHeight: "100vh" }}>
      {/* Top Announcement Banner */}
      <div 
        style={{ 
          background: "linear-gradient(90deg, #4A154B 0%, #611f69 50%, #0fb5a1 100%)", 
          color: "#ffffff", 
          padding: "10px 16px", 
          textAlign: "center", 
          fontSize: "13.5px", 
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "8px",
          flexWrap: "wrap"
        }}
      >
        <span style={{ 
          background: "rgba(255,255,255,0.2)", 
          padding: "2px 8px", 
          borderRadius: "999px", 
          fontSize: "11px", 
          textTransform: "uppercase", 
          letterSpacing: "0.05em" 
        }}>
          New Integration
        </span>
        <span>GSearchAI is now available for Slack. Search company docs without leaving your channels.</span>
        <a 
          href="#install-steps" 
          style={{ 
            color: "#ffffff", 
            textDecoration: "underline", 
            fontWeight: 700, 
            marginLeft: "4px" 
          }}
        >
          View Quickstart →
        </a>
      </div>

      {/* Header / Navigation Bar */}
      <header 
        style={{ 
          borderBottom: "1px solid #eef2f6", 
          position: "sticky", 
          top: 0, 
          background: "rgba(255, 255, 255, 0.95)", 
          backdropFilter: "blur(12px)", 
          zIndex: 90 
        }}
      >
        <div 
          style={{ 
            maxWidth: "1200px", 
            margin: "0 auto", 
            padding: "16px 24px", 
            display: "flex", 
            alignItems: "center", 
            justifyContent: "space-between" 
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <Link href="/" style={{ display: "flex", alignItems: "center" }}>
              <BrandGlyph height={34} />
            </Link>
            <span style={{ color: "#d9dfe8", fontSize: "20px" }}>/</span>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 700, color: "#4A154B", fontSize: "15px" }}>
              <FaSlack style={{ fontSize: "20px", color: "#4A154B" }} />
              <span>Slack App</span>
            </div>
          </div>

          <nav style={{ display: "flex", alignItems: "center", gap: "28px" }} className="desktop-nav">
            <a href="#overview" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>Overview</a>
            <a href="#how-it-works" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>How It Works</a>
            <a href="#install-steps" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>Installation</a>
            <a href="#commands" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>Commands</a>
            <a href="#security" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>Security</a>
            <a href="#faq" style={{ fontSize: "14.5px", fontWeight: 600, color: "#414856" }}>FAQ</a>
            <Link href="/support" style={{ fontSize: "14.5px", fontWeight: 600, color: "#0a8576" }}>Support</Link>
          </nav>

          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <Link 
              href="/login" 
              style={{ 
                fontSize: "14.5px", 
                fontWeight: 600, 
                color: "#14161f", 
                padding: "8px 16px" 
              }}
            >
              Sign In
            </Link>
            <a
              href={slackInstallUrl}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                background: "#4A154B",
                color: "#ffffff",
                padding: "9px 18px",
                borderRadius: "10px",
                fontWeight: 700,
                fontSize: "14px",
                boxShadow: "0 2px 8px rgba(74, 21, 75, 0.25)",
                transition: "all 0.2s ease"
              }}
            >
              <FaSlack style={{ fontSize: "16px" }} />
              <span>Add to Slack</span>
            </a>
          </div>
        </div>
      </header>

      {/* Hero Section */}
      <section 
        id="overview"
        style={{ 
          padding: "64px 24px 72px", 
          background: "radial-gradient(ellipse at 50% 0%, rgba(74, 21, 75, 0.05) 0%, rgba(15, 181, 161, 0.03) 50%, #ffffff 100%)",
          borderBottom: "1px solid #eef2f6"
        }}
      >
        <div style={{ maxWidth: "1140px", margin: "0 auto", textAlign: "center" }}>
          {/* Eyebrow badge */}
          <div 
            style={{ 
              display: "inline-flex", 
              alignItems: "center", 
              gap: "8px", 
              background: "#e3f7f3", 
              color: "#0a8576", 
              padding: "6px 14px", 
              borderRadius: "999px", 
              fontSize: "13px", 
              fontWeight: 700,
              marginBottom: "20px" 
            }}
          >
            <FaSlack style={{ color: "#4A154B", fontSize: "15px" }} />
            <span>Official GSearchAI Slack Integration</span>
            <span style={{ width: "4px", height: "4px", borderRadius: "50%", background: "#0a8576" }} />
            <span>Direct Enterprise Search</span>
          </div>

          <h1 
            style={{ 
              fontSize: "clamp(34px, 5vw, 54px)", 
              fontWeight: 800, 
              color: "#14161f", 
              letterSpacing: "-0.03em", 
              lineHeight: 1.15, 
              maxWidth: "880px", 
              margin: "0 auto 20px" 
            }}
          >
            Your Company Knowledge Base,{" "}
            <span 
              style={{ 
                background: "linear-gradient(135deg, #4A154B 0%, #0fb5a1 100%)", 
                WebkitBackgroundClip: "text", 
                WebkitTextFillColor: "transparent" 
              }}
            >
              Instant In Slack
            </span>
          </h1>

          <p 
            style={{ 
              fontSize: "clamp(16px, 2vw, 19px)", 
              color: "#414856", 
              lineHeight: 1.6, 
              maxWidth: "760px", 
              margin: "0 auto 36px" 
            }}
          >
            Eliminate silos and stop repeating yourself in channels. Mention <strong>@GSearchAI</strong> or type <strong>/gsearch</strong> to query documents across Google Drive, Notion, Confluence, Jira, and internal wikis with exact citation links and zero hallucinations.
          </p>

          {/* Primary CTA Buttons including Official Slack Button */}
          <div 
            style={{ 
              display: "flex", 
              alignItems: "center", 
              justifyContent: "center", 
              gap: "16px", 
              flexWrap: "wrap", 
              marginBottom: "36px" 
            }}
          >
            {/* Official Slack Add to Slack Button standard image */}
            <a 
              href={slackInstallUrl}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "transform 0.15s ease",
                height: "48px"
              }}
              title="Add to Slack"
            >
              <img 
                alt="Add to Slack" 
                height="44" 
                width="153" 
                src="https://platform.slack-edge.com/img/add_to_slack.png" 
                srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                style={{ borderRadius: "8px", boxShadow: "0 3px 12px rgba(0,0,0,0.12)" }}
              />
            </a>

            {/* Direct Connect / Setup Button */}
            <button
              onClick={() => setIsModalOpen(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "10px",
                background: "#0fb5a1",
                color: "#ffffff",
                padding: "12px 24px",
                borderRadius: "10px",
                fontWeight: 700,
                fontSize: "15px",
                border: "none",
                cursor: "pointer",
                boxShadow: "0 4px 14px rgba(15, 181, 161, 0.35)",
                transition: "all 0.2s ease"
              }}
            >
              <span>Install via GSearchAI</span>
              <FaArrowRight style={{ fontSize: "14px" }} />
            </button>

            <a
              href="#how-it-works"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                background: "#f5f7fa",
                color: "#14161f",
                padding: "12px 22px",
                borderRadius: "10px",
                fontWeight: 600,
                fontSize: "15px",
                border: "1px solid #d9dfe8",
                transition: "all 0.2s ease"
              }}
            >
              <FaBolt style={{ color: "#f4c24b" }} />
              <span>See Demo Preview</span>
            </a>
          </div>

          {/* Quick trust metrics */}
          <div 
            style={{ 
              display: "flex", 
              alignItems: "center", 
              justifyContent: "center", 
              gap: "28px", 
              color: "#6b7280", 
              fontSize: "13.5px", 
              flexWrap: "wrap" 
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <FaCircleCheck style={{ color: "#0fb5a1" }} />
              <span>OAuth 2.0 Secure Grant</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <FaCircleCheck style={{ color: "#0fb5a1" }} />
              <span>Role-Based Access Control</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <FaCircleCheck style={{ color: "#0fb5a1" }} />
              <span>Zero LLM Data Retention</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <FaCircleCheck style={{ color: "#0fb5a1" }} />
              <span>Post-Install Redirect & Setup</span>
            </div>
          </div>
        </div>
      </section>

      {/* Visual Explanation: High-Fidelity Slack Interactive Simulator */}
      <section 
        id="how-it-works"
        style={{ 
          padding: "72px 24px", 
          background: "#fafbfc", 
          borderBottom: "1px solid #eef2f6" 
        }}
      >
        <div style={{ maxWidth: "1140px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "44px" }}>
            <div 
              style={{ 
                color: "#0a8576", 
                fontWeight: 700, 
                textTransform: "uppercase", 
                fontSize: "12px", 
                letterSpacing: "0.08em", 
                marginBottom: "8px" 
              }}
            >
              Experience in Action
            </div>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 38px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              How GSearchAI Works Directly in Slack
            </h2>
            <p style={{ fontSize: "16px", color: "#414856", maxWidth: "680px", margin: "0 auto" }}>
              Explore how your team interacts with the bot. No tab switching, no logging into separate portals — just natural collaboration.
            </p>
          </div>

          {/* Interactive Mode Selector Tabs */}
          <div 
            style={{ 
              display: "flex", 
              justifyContent: "center", 
              gap: "8px", 
              marginBottom: "32px", 
              flexWrap: "wrap" 
            }}
          >
            <button
              onClick={() => setActiveTab("channel")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 20px",
                borderRadius: "30px",
                fontWeight: 700,
                fontSize: "14px",
                border: "none",
                cursor: "pointer",
                background: activeTab === "channel" ? "#4A154B" : "#ffffff",
                color: activeTab === "channel" ? "#ffffff" : "#414856",
                boxShadow: activeTab === "channel" ? "0 4px 12px rgba(74, 21, 75, 0.2)" : "0 1px 4px rgba(0,0,0,0.06)",
                borderWidth: "1px",
                borderStyle: "solid",
                borderColor: activeTab === "channel" ? "#4A154B" : "#e5e9ef"
              }}
            >
              <FaComments />
              <span>1. Channel Mention (@GSearchAI)</span>
            </button>

            <button
              onClick={() => setActiveTab("slash")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 20px",
                borderRadius: "30px",
                fontWeight: 700,
                fontSize: "14px",
                border: "none",
                cursor: "pointer",
                background: activeTab === "slash" ? "#4A154B" : "#ffffff",
                color: activeTab === "slash" ? "#ffffff" : "#414856",
                boxShadow: activeTab === "slash" ? "0 4px 12px rgba(74, 21, 75, 0.2)" : "0 1px 4px rgba(0,0,0,0.06)",
                borderWidth: "1px",
                borderStyle: "solid",
                borderColor: activeTab === "slash" ? "#4A154B" : "#e5e9ef"
              }}
            >
              <FaMagnifyingGlass />
              <span>2. Slash Command (/gsearch)</span>
            </button>

            <button
              onClick={() => setActiveTab("thread")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                padding: "10px 20px",
                borderRadius: "30px",
                fontWeight: 700,
                fontSize: "14px",
                border: "none",
                cursor: "pointer",
                background: activeTab === "thread" ? "#4A154B" : "#ffffff",
                color: activeTab === "thread" ? "#ffffff" : "#414856",
                boxShadow: activeTab === "thread" ? "0 4px 12px rgba(74, 21, 75, 0.2)" : "0 1px 4px rgba(0,0,0,0.06)",
                borderWidth: "1px",
                borderStyle: "solid",
                borderColor: activeTab === "thread" ? "#4A154B" : "#e5e9ef"
              }}
            >
              <FaFileLines />
              <span>3. Verified Citations & Access Control</span>
            </button>
          </div>

          {/* Slack Window Frame Mockup */}
          <div 
            style={{ 
              background: "#1A1D21", 
              borderRadius: "16px", 
              boxShadow: "0 20px 50px -10px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(255,255,255,0.08)", 
              overflow: "hidden", 
              border: "1px solid #2d3136" 
            }}
          >
            {/* Slack Top Bar */}
            <div 
              style={{ 
                background: "#121518", 
                padding: "12px 20px", 
                display: "flex", 
                alignItems: "center", 
                justifyContent: "space-between", 
                borderBottom: "1px solid #2c3136" 
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#EC6A5E" }} />
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#F4BF4F" }} />
                <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: "#61C554" }} />
                <span style={{ marginLeft: "12px", color: "#ABABAD", fontSize: "13px", fontWeight: 600 }}>
                  Acme Corp Workspace &bull; #product-team
                </span>
              </div>
              <div 
                style={{ 
                  background: "#222529", 
                  padding: "4px 16px", 
                  borderRadius: "6px", 
                  fontSize: "12px", 
                  color: "#ABABAD",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px"
                }}
              >
                <FaMagnifyingGlass style={{ fontSize: "11px" }} />
                <span>Search in Acme Corp</span>
              </div>
            </div>

            {/* Slack Main Chat Area */}
            <div style={{ padding: "28px 24px", background: "#1A1D21", minHeight: "360px" }}>
              {activeTab === "channel" && (
                <div>
                  {/* User Query Message */}
                  <div style={{ display: "flex", gap: "14px", marginBottom: "24px" }}>
                    <div 
                      style={{ 
                        width: "40px", 
                        height: "40px", 
                        borderRadius: "8px", 
                        background: "#3b82f6", 
                        color: "#fff", 
                        display: "flex", 
                        alignItems: "center", 
                        justifyContent: "center", 
                        fontWeight: 700,
                        fontSize: "15px",
                        flexShrink: 0
                      }}
                    >
                      SJ
                    </div>
                    <div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#FFFFFF", fontWeight: 700, fontSize: "15px" }}>Sarah Jenkins</span>
                        <span style={{ color: "#868688", fontSize: "12px" }}>11:42 AM</span>
                      </div>
                      <div style={{ color: "#D1D2D3", fontSize: "14.5px", lineHeight: 1.5 }}>
                        <span style={{ background: "rgba(15, 181, 161, 0.25)", color: "#2dd4bf", padding: "2px 6px", borderRadius: "4px", fontWeight: 600 }}>
                          @GSearchAI
                        </span>{" "}
                        What is our standard security retention policy for customer database backups according to our SOC2 report?
                      </div>
                    </div>
                  </div>

                  {/* GSearchAI Bot Response */}
                  <div 
                    style={{ 
                      display: "flex", 
                      gap: "14px", 
                      background: "rgba(74, 21, 75, 0.15)", 
                      padding: "16px", 
                      borderRadius: "10px", 
                      borderLeft: "4px solid #0fb5a1" 
                    }}
                  >
                    <div 
                      style={{ 
                        width: "40px", 
                        height: "40px", 
                        borderRadius: "8px", 
                        background: "#0fb5a1", 
                        display: "flex", 
                        alignItems: "center", 
                        justifyContent: "center", 
                        flexShrink: 0 
                      }}
                    >
                      <img src="/512_512.png" alt="GSearchAI" style={{ width: "28px", height: "28px", borderRadius: "4px" }} />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginBottom: "6px" }}>
                        <span style={{ color: "#FFFFFF", fontWeight: 700, fontSize: "15px" }}>GSearchAI</span>
                        <span style={{ background: "#4A154B", color: "#FFFFFF", fontSize: "10px", fontWeight: 700, padding: "1px 6px", borderRadius: "4px" }}>
                          APP
                        </span>
                        <span style={{ color: "#868688", fontSize: "12px" }}>11:42 AM</span>
                      </div>

                      <div style={{ color: "#E0E0E0", fontSize: "14px", lineHeight: 1.6, marginBottom: "16px" }}>
                        According to your organization&apos;s <strong>SOC 2 Type II Security Standard &amp; Backup Policy</strong>:
                        <ul style={{ margin: "8px 0 12px 18px", padding: 0 }}>
                          <li><strong>Daily Snapshot Backups:</strong> Retained for <strong>30 calendar days</strong> with automated SHA-256 integrity validation.</li>
                          <li><strong>Monthly Cold Storage Backups:</strong> Encrypted using <strong>AES-256</strong> and retained for <strong>365 days (1 year)</strong> in multi-region cloud vaults.</li>
                          <li><strong>Deletion Protocol:</strong> Customer data upon contractual termination is purged within <strong>14 business days</strong> upon validated tenant request.</li>
                        </ul>
                      </div>

                      {/* Slack Source Citations Block */}
                      <div 
                        style={{ 
                          background: "#222529", 
                          padding: "12px 16px", 
                          borderRadius: "8px", 
                          border: "1px solid #36393e" 
                        }}
                      >
                        <div style={{ fontSize: "12px", fontWeight: 700, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px" }}>
                          Verified Source Citations (2 References Found)
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                          <a 
                            href="#sources" 
                            style={{ 
                              display: "flex", 
                              alignItems: "center", 
                              justifyContent: "space-between", 
                              background: "#181a1d", 
                              padding: "8px 12px", 
                              borderRadius: "6px", 
                              color: "#60a5fa", 
                              fontSize: "13px", 
                              textDecoration: "none" 
                            }}
                          >
                            <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <FaGoogleDrive style={{ color: "#34a853" }} />
                              <strong style={{ color: "#ffffff" }}>[1] SOC2_Type_II_Compliance_2026.pdf</strong> (Section 4.3 &bull; Page 19)
                            </span>
                            <FaArrowUpRightFromSquare style={{ fontSize: "12px", color: "#9ca3af" }} />
                          </a>

                          <a 
                            href="#sources" 
                            style={{ 
                              display: "flex", 
                              alignItems: "center", 
                              justifyContent: "space-between", 
                              background: "#181a1d", 
                              padding: "8px 12px", 
                              borderRadius: "6px", 
                              color: "#60a5fa", 
                              fontSize: "13px", 
                              textDecoration: "none" 
                            }}
                          >
                            <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <SiConfluence style={{ color: "#0052cc" }} />
                              <strong style={{ color: "#ffffff" }}>[2] Engineering Wiki: Disaster Recovery Playbook</strong> (Last updated 3 weeks ago)
                            </span>
                            <FaArrowUpRightFromSquare style={{ fontSize: "12px", color: "#9ca3af" }} />
                          </a>
                        </div>
                      </div>

                      {/* Slack Block Kit Action Buttons */}
                      <div style={{ display: "flex", gap: "8px", marginTop: "14px", flexWrap: "wrap" }}>
                        <button 
                          style={{ 
                            background: "#222529", 
                            color: "#D1D2D3", 
                            border: "1px solid #36393e", 
                            borderRadius: "6px", 
                            padding: "6px 12px", 
                            fontSize: "12.5px", 
                            fontWeight: 600,
                            cursor: "pointer"
                          }}
                        >
                          Copy Answer
                        </button>
                        <button 
                          style={{ 
                            background: "#222529", 
                            color: "#D1D2D3", 
                            border: "1px solid #36393e", 
                            borderRadius: "6px", 
                            padding: "6px 12px", 
                            fontSize: "12.5px", 
                            fontWeight: 600,
                            cursor: "pointer"
                          }}
                        >
                          Ask Follow-up
                        </button>
                        <button 
                          style={{ 
                            background: "#222529", 
                            color: "#10b981", 
                            border: "1px solid #36393e", 
                            borderRadius: "6px", 
                            padding: "6px 12px", 
                            fontSize: "12.5px", 
                            fontWeight: 600,
                            cursor: "pointer"
                          }}
                        >
                          👍 Helpful
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === "slash" && (
                <div>
                  {/* Slash command typing */}
                  <div style={{ display: "flex", gap: "14px", marginBottom: "20px" }}>
                    <div 
                      style={{ 
                        width: "40px", 
                        height: "40px", 
                        borderRadius: "8px", 
                        background: "#10b981", 
                        color: "#fff", 
                        display: "flex", 
                        alignItems: "center", 
                        justifyContent: "center", 
                        fontWeight: 700,
                        fontSize: "15px",
                        flexShrink: 0
                      }}
                    >
                      MK
                    </div>
                    <div>
                      <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#FFFFFF", fontWeight: 700, fontSize: "15px" }}>Marcus Kim</span>
                        <span style={{ color: "#868688", fontSize: "12px" }}>2:15 PM</span>
                      </div>
                      <div style={{ color: "#D1D2D3", fontSize: "14.5px", fontFamily: "monospace" }}>
                        <span style={{ color: "#f59e0b", fontWeight: 700 }}>/gsearch</span> quarterly revenue targets Q4 enterprise plan
                      </div>
                    </div>
                  </div>

                  {/* Ephemeral Slack Response */}
                  <div 
                    style={{ 
                      background: "#222529", 
                      padding: "16px 20px", 
                      borderRadius: "10px", 
                      border: "1px solid #36393e" 
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
                      <span style={{ color: "#9ca3af", fontSize: "12px", fontStyle: "italic" }}>
                        Only visible to you &bull; Ephemeral result
                      </span>
                      <span style={{ background: "#374151", color: "#d1d5db", fontSize: "11px", padding: "2px 8px", borderRadius: "4px" }}>
                        Found in 0.42s
                      </span>
                    </div>

                    <div style={{ color: "#FFFFFF", fontSize: "14.5px", fontWeight: 600, marginBottom: "8px" }}>
                      Q4 Enterprise Revenue Target: $4.2M ARR (18% QoQ Growth)
                    </div>
                    <div style={{ color: "#d1d5db", fontSize: "13.5px", lineHeight: 1.5, marginBottom: "14px" }}>
                      Key driver is expanding the Tier-1 Enterprise seat licensing and onboarding 24 targeted accounts outlined in the Go-To-Market strategy.
                    </div>

                    <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                      <div style={{ background: "#181a1d", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", color: "#93c5fd" }}>
                        📄 Google Sheet: FY26_Financial_Forecast_v3.xlsx
                      </div>
                      <div style={{ background: "#181a1d", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", color: "#93c5fd" }}>
                        📌 Notion: Executive Strategy &amp; Milestones
                      </div>
                    </div>

                    <div style={{ marginTop: "14px", display: "flex", gap: "8px" }}>
                      <button style={{ background: "#4A154B", color: "#fff", border: "none", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", fontWeight: 600, cursor: "pointer" }}>
                        Post to Channel
                      </button>
                      <button style={{ background: "#374151", color: "#d1d5db", border: "none", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", fontWeight: 600, cursor: "pointer" }}>
                        Dismiss
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === "thread" && (
                <div>
                  <div 
                    style={{ 
                      background: "rgba(15, 181, 161, 0.08)", 
                      border: "1px solid rgba(15, 181, 161, 0.3)", 
                      padding: "16px 20px", 
                      borderRadius: "10px", 
                      marginBottom: "16px" 
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#2dd4bf", fontWeight: 700, fontSize: "14px", marginBottom: "8px" }}>
                      <FaShieldHalved />
                      <span>Enterprise Permission Inheritance (Zero Leakage)</span>
                    </div>
                    <p style={{ color: "#d1d5db", fontSize: "13.5px", lineHeight: 1.5, margin: 0 }}>
                      GSearchAI automatically mirrors your existing authorization rules. If an engineer searches Slack, they will never see confidential HR compensation spreadsheets or unshared executive folders unless their enterprise account already has permission in Google Drive, Notion, or Confluence.
                    </p>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "12px" }}>
                    <div style={{ background: "#222529", padding: "14px", borderRadius: "8px", border: "1px solid #36393e" }}>
                      <div style={{ color: "#10b981", fontWeight: 700, fontSize: "13px", marginBottom: "4px" }}>
                        ✓ Granular File Permissions
                      </div>
                      <div style={{ color: "#9ca3af", fontSize: "12.5px" }}>
                        Inherits Google Drive &amp; Confluence ACLs in real time.
                      </div>
                    </div>
                    <div style={{ background: "#222529", padding: "14px", borderRadius: "8px", border: "1px solid #36393e" }}>
                      <div style={{ color: "#10b981", fontWeight: 700, fontSize: "13px", marginBottom: "4px" }}>
                        ✓ Direct Link Citations
                      </div>
                      <div style={{ color: "#9ca3af", fontSize: "12.5px" }}>
                        Every answer pinpoints the exact file, section, and page number.
                      </div>
                    </div>
                    <div style={{ background: "#222529", padding: "14px", borderRadius: "8px", border: "1px solid #36393e" }}>
                      <div style={{ color: "#10b981", fontWeight: 700, fontSize: "13px", marginBottom: "4px" }}>
                        ✓ SOC 2 &amp; GDPR Ready
                      </div>
                      <div style={{ color: "#9ca3af", fontSize: "12.5px" }}>
                        Data is encrypted at rest (AES-256) and never used to train public LLMs.
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Slack input bar simulation */}
            <div 
              style={{ 
                background: "#222529", 
                padding: "12px 20px", 
                borderTop: "1px solid #2d3136", 
                display: "flex", 
                alignItems: "center", 
                justifyContent: "space-between" 
              }}
            >
              <span style={{ color: "#7a7d81", fontSize: "13.5px" }}>
                Send a message to #product-team or try @GSearchAI...
              </span>
              <div style={{ display: "flex", gap: "8px" }}>
                <span style={{ background: "#2e3238", padding: "4px 8px", borderRadius: "4px", fontSize: "11px", color: "#a0a5ad" }}>
                  Ctrl + Enter to send
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* The Problem GSearchAI Solves & Features */}
      <section style={{ padding: "72px 24px", background: "#ffffff", borderBottom: "1px solid #eef2f6" }}>
        <div style={{ maxWidth: "1140px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "48px" }}>
            <div style={{ color: "#0a8576", fontWeight: 700, textTransform: "uppercase", fontSize: "12px", letterSpacing: "0.08em", marginBottom: "8px" }}>
              Enterprise Productivity
            </div>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 36px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              Why Teams Need GSearchAI in Slack
            </h2>
            <p style={{ fontSize: "16px", color: "#414856", maxWidth: "680px", margin: "0 auto" }}>
              Information fragmentation wastes hours every day. GSearchAI bridges all company tools into the chat platform where teams already collaborate.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "24px" }}>
            {/* Feature 1 */}
            <div 
              style={{ 
                background: "#f9fafb", 
                padding: "32px 28px", 
                borderRadius: "16px", 
                border: "1px solid #e5e9ef",
                transition: "transform 0.2s ease"
              }}
            >
              <div 
                style={{ 
                  width: "48px", 
                  height: "48px", 
                  borderRadius: "12px", 
                  background: "#e3f7f3", 
                  color: "#0a8576", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontSize: "22px", 
                  marginBottom: "20px" 
                }}
              >
                <FaMagnifyingGlass />
              </div>
              <h3 style={{ fontSize: "20px", fontWeight: 700, color: "#14161f", marginBottom: "10px" }}>
                Multi-Connector Search
              </h3>
              <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, margin: 0 }}>
                Query Google Drive folders, Jira sprint boards, Notion wikis, Confluence pages, and GitHub repositories simultaneously. No more asking teammates &quot;where was that file?&quot;
              </p>
            </div>

            {/* Feature 2 */}
            <div 
              style={{ 
                background: "#f9fafb", 
                padding: "32px 28px", 
                borderRadius: "16px", 
                border: "1px solid #e5e9ef",
                transition: "transform 0.2s ease"
              }}
            >
              <div 
                style={{ 
                  width: "48px", 
                  height: "48px", 
                  borderRadius: "12px", 
                  background: "rgba(74, 21, 75, 0.1)", 
                  color: "#4A154B", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontSize: "22px", 
                  marginBottom: "20px" 
                }}
              >
                <FaFileLines />
              </div>
              <h3 style={{ fontSize: "20px", fontWeight: 700, color: "#14161f", marginBottom: "10px" }}>
                Direct Source Verifiability
              </h3>
              <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, margin: 0 }}>
                Every synthesized answer in Slack includes interactive citation chips pointing directly to the exact file, document paragraph, or Jira ticket, so decisions are always anchored in facts.
              </p>
            </div>

            {/* Feature 3 */}
            <div 
              style={{ 
                background: "#f9fafb", 
                padding: "32px 28px", 
                borderRadius: "16px", 
                border: "1px solid #e5e9ef",
                transition: "transform 0.2s ease"
              }}
            >
              <div 
                style={{ 
                  width: "48px", 
                  height: "48px", 
                  borderRadius: "12px", 
                  background: "rgba(124, 108, 240, 0.12)", 
                  color: "#7c6cf0", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontSize: "22px", 
                  marginBottom: "20px" 
                }}
              >
                <FaLock />
              </div>
              <h3 style={{ fontSize: "20px", fontWeight: 700, color: "#14161f", marginBottom: "10px" }}>
                Strict Workspace Privacy
              </h3>
              <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, margin: 0 }}>
                GSearchAI respects existing authorization policies. Users only receive answers from documents they have permission to see. Confidential data remains strictly confidential.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Clear Path to Installing Your Slack App */}
      <section 
        id="install-steps" 
        style={{ 
          padding: "72px 24px", 
          background: "linear-gradient(180deg, #fafbfc 0%, #ffffff 100%)", 
          borderBottom: "1px solid #eef2f6" 
        }}
      >
        <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "48px" }}>
            <div style={{ color: "#0a8576", fontWeight: 700, textTransform: "uppercase", fontSize: "12px", letterSpacing: "0.08em", marginBottom: "8px" }}>
              Installation &amp; Setup Guide
            </div>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 36px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              How to Install GSearchAI in Your Slack Workspace
            </h2>
            <p style={{ fontSize: "16px", color: "#414856", maxWidth: "660px", margin: "0 auto" }}>
              Installation takes less than two minutes. Follow the clear steps below to connect your Slack workspace with GSearchAI.
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {/* Step 1 */}
            <div 
              style={{ 
                background: "#ffffff", 
                border: "1px solid #e5e9ef", 
                borderRadius: "14px", 
                padding: "24px 28px", 
                display: "flex", 
                gap: "20px", 
                alignItems: "flex-start",
                boxShadow: "0 2px 8px rgba(0,0,0,0.02)"
              }}
            >
              <div 
                style={{ 
                  width: "42px", 
                  height: "42px", 
                  borderRadius: "50%", 
                  background: "#4A154B", 
                  color: "#ffffff", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontWeight: 800, 
                  fontSize: "17px",
                  flexShrink: 0 
                }}
              >
                1
              </div>
              <div style={{ flex: 1 }}>
                <h4 style={{ fontSize: "18px", fontWeight: 700, color: "#14161f", marginBottom: "6px" }}>
                  Click &quot;Add to Slack&quot; or Connect from GSearchAI Dashboard
                </h4>
                <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, marginBottom: "14px" }}>
                  You can install directly using the official Slack authorization button below, or sign in to your GSearchAI Dashboard, navigate to <strong>Integrations &gt; Slack</strong>, and click <strong>Connect Workspace</strong>.
                </p>
                <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
                  <a 
                    href={slackInstallUrl} 
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "8px",
                      background: "#4A154B",
                      color: "#ffffff",
                      padding: "8px 16px",
                      borderRadius: "8px",
                      fontWeight: 700,
                      fontSize: "13.5px"
                    }}
                  >
                    <FaSlack />
                    <span>Authorize with Slack</span>
                  </a>
                  <Link 
                    href="/dashboard/integrations" 
                    style={{ 
                      fontSize: "13.5px", 
                      color: "#0a8576", 
                      fontWeight: 600, 
                      textDecoration: "underline" 
                    }}
                  >
                    Open GSearchAI Integrations Settings →
                  </Link>
                </div>
              </div>
            </div>

            {/* Step 2 */}
            <div 
              style={{ 
                background: "#ffffff", 
                border: "1px solid #e5e9ef", 
                borderRadius: "14px", 
                padding: "24px 28px", 
                display: "flex", 
                gap: "20px", 
                alignItems: "flex-start",
                boxShadow: "0 2px 8px rgba(0,0,0,0.02)"
              }}
            >
              <div 
                style={{ 
                  width: "42px", 
                  height: "42px", 
                  borderRadius: "50%", 
                  background: "#4A154B", 
                  color: "#ffffff", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontWeight: 800, 
                  fontSize: "17px",
                  flexShrink: 0 
                }}
              >
                2
              </div>
              <div style={{ flex: 1 }}>
                <h4 style={{ fontSize: "18px", fontWeight: 700, color: "#14161f", marginBottom: "6px" }}>
                  Authorize Permissions in Slack
                </h4>
                <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, margin: 0 }}>
                  Slack will prompt you to choose the target workspace and review requested scopes (e.g. <code>app_mentions:read</code>, <code>chat:write</code>, <code>commands</code>). Click <strong>Allow</strong>. GSearchAI only requests the minimal permissions required to listen to mentions and respond with search answers.
                </p>
              </div>
            </div>

            {/* Step 3 */}
            <div 
              style={{ 
                background: "#ffffff", 
                border: "1px solid #e5e9ef", 
                borderRadius: "14px", 
                padding: "24px 28px", 
                display: "flex", 
                gap: "20px", 
                alignItems: "flex-start",
                boxShadow: "0 2px 8px rgba(0,0,0,0.02)"
              }}
            >
              <div 
                style={{ 
                  width: "42px", 
                  height: "42px", 
                  borderRadius: "50%", 
                  background: "#4A154B", 
                  color: "#ffffff", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontWeight: 800, 
                  fontSize: "17px",
                  flexShrink: 0 
                }}
              >
                3
              </div>
              <div style={{ flex: 1 }}>
                <h4 style={{ fontSize: "18px", fontWeight: 700, color: "#14161f", marginBottom: "6px" }}>
                  Confirmation &amp; Workspace Pairing
                </h4>
                <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, margin: 0 }}>
                  Once authorization succeeds, Slack automatically redirects you to our{" "}
                  <Link href="/slack/success" style={{ color: "#0a8576", fontWeight: 700, textDecoration: "underline" }}>
                    Installation Confirmation Page
                  </Link>
                  , validating the connection and presenting clear immediate next steps to test GSearchAI in your team channels.
                </p>
              </div>
            </div>

            {/* Step 4 */}
            <div 
              style={{ 
                background: "#ffffff", 
                border: "1px solid #e5e9ef", 
                borderRadius: "14px", 
                padding: "24px 28px", 
                display: "flex", 
                gap: "20px", 
                alignItems: "flex-start",
                boxShadow: "0 2px 8px rgba(0,0,0,0.02)"
              }}
            >
              <div 
                style={{ 
                  width: "42px", 
                  height: "42px", 
                  borderRadius: "50%", 
                  background: "#4A154B", 
                  color: "#ffffff", 
                  display: "flex", 
                  alignItems: "center", 
                  justifyContent: "center", 
                  fontWeight: 800, 
                  fontSize: "17px",
                  flexShrink: 0 
                }}
              >
                4
              </div>
              <div style={{ flex: 1 }}>
                <h4 style={{ fontSize: "18px", fontWeight: 700, color: "#14161f", marginBottom: "6px" }}>
                  Invite @GSearchAI to Team Channels
                </h4>
                <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, marginBottom: "10px" }}>
                  Invite the bot into any public or private channel where your team asks questions by running the invite command:
                </p>
                <div 
                  style={{ 
                    display: "inline-flex", 
                    alignItems: "center", 
                    gap: "10px", 
                    background: "#f1f5f9", 
                    padding: "8px 14px", 
                    borderRadius: "8px", 
                    fontFamily: "monospace", 
                    fontSize: "13.5px", 
                    color: "#1e293b" 
                  }}
                >
                  <span>/invite @GSearchAI</span>
                  <button 
                    onClick={() => handleCopy("/invite @GSearchAI", "invite")}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", padding: 0 }}
                    title="Copy command"
                  >
                    {copiedCommand === "invite" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Clear Path to Using Your App: Commands & Usage Guide */}
      <section 
        id="commands" 
        style={{ 
          padding: "72px 24px", 
          background: "#ffffff", 
          borderBottom: "1px solid #eef2f6" 
        }}
      >
        <div style={{ maxWidth: "1140px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "48px" }}>
            <div style={{ color: "#0a8576", fontWeight: 700, textTransform: "uppercase", fontSize: "12px", letterSpacing: "0.08em", marginBottom: "8px" }}>
              Quickstart &amp; Commands
            </div>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 36px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              How to Use GSearchAI After Installing
            </h2>
            <p style={{ fontSize: "16px", color: "#414856", maxWidth: "680px", margin: "0 auto" }}>
              Here are the exact ways your team can interact with GSearchAI once added to your workspace.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "20px" }}>
            {/* Command 1 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "14px", padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ background: "#4A154B", color: "#ffffff", padding: "4px 10px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px", fontWeight: 700 }}>
                  @GSearchAI [question]
                </span>
                <button 
                  onClick={() => handleCopy("@GSearchAI What is our Q4 marketing plan?", "cmd1")}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                  title="Copy sample"
                >
                  {copiedCommand === "cmd1" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                </button>
              </div>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Ask in any Channel
              </h4>
              <p style={{ fontSize: "13.5px", color: "#64748b", lineHeight: 1.5, margin: 0 }}>
                Tag the bot in any thread or public channel. The bot analyzes all connected company documents, synthesizes a concise response, and posts citations right in the channel.
              </p>
            </div>

            {/* Command 2 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "14px", padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ background: "#0fb5a1", color: "#ffffff", padding: "4px 10px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px", fontWeight: 700 }}>
                  /gsearch [search terms]
                </span>
                <button 
                  onClick={() => handleCopy("/gsearch remote work expense policy", "cmd2")}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b" }}
                  title="Copy sample"
                >
                  {copiedCommand === "cmd2" ? <FaCheck style={{ color: "#10b981" }} /> : <FaCopy />}
                </button>
              </div>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Private Slash Search
              </h4>
              <p style={{ fontSize: "13.5px", color: "#64748b", lineHeight: 1.5, margin: 0 }}>
                Run quick ephemeral searches without cluttering public channels. You alone see the results, with an option to post the answer to the channel if desired.
              </p>
            </div>

            {/* Command 3 */}
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "14px", padding: "24px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
                <span style={{ background: "#7c6cf0", color: "#ffffff", padding: "4px 10px", borderRadius: "6px", fontFamily: "monospace", fontSize: "13px", fontWeight: 700 }}>
                  Direct Message
                </span>
                <span style={{ color: "#94a3b8", fontSize: "12px" }}>1-on-1 Chat</span>
              </div>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Private AI Research Assistant
              </h4>
              <p style={{ fontSize: "13.5px", color: "#64748b", lineHeight: 1.5, margin: 0 }}>
                Open a direct message with GSearchAI in your Slack sidebar for confidential questions, drafting proposals based on internal knowledge, or exploratory research.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Permissions Transparency & Security Section */}
      <section 
        id="security" 
        style={{ 
          padding: "72px 24px", 
          background: "#fafbfc", 
          borderBottom: "1px solid #eef2f6" 
        }}
      >
        <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "44px" }}>
            <div style={{ color: "#0a8576", fontWeight: 700, textTransform: "uppercase", fontSize: "12px", letterSpacing: "0.08em", marginBottom: "8px" }}>
              Trust &amp; Governance
            </div>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 36px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              Permissions Transparency &amp; Security Standards
            </h2>
            <p style={{ fontSize: "16px", color: "#414856", maxWidth: "680px", margin: "0 auto" }}>
              We adhere to the highest enterprise security standards. Here is exactly what permissions GSearchAI requests and why.
            </p>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "14px", overflow: "hidden", marginBottom: "32px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "14px" }}>
              <thead>
                <tr style={{ background: "#f8fafc", borderBottom: "1px solid #e2e8f0" }}>
                  <th style={{ padding: "14px 20px", fontWeight: 700, color: "#1e293b" }}>Slack OAuth Scope</th>
                  <th style={{ padding: "14px 20px", fontWeight: 700, color: "#1e293b" }}>Scope Type</th>
                  <th style={{ padding: "14px 20px", fontWeight: 700, color: "#1e293b" }}>Why GSearchAI Needs It</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 20px", fontFamily: "monospace", color: "#4A154B", fontWeight: 600 }}>app_mentions:read</td>
                  <td style={{ padding: "14px 20px", color: "#64748b" }}>Bot</td>
                  <td style={{ padding: "14px 20px", color: "#334155" }}>To receive queries whenever a teammate mentions @GSearchAI in a channel.</td>
                </tr>
                <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 20px", fontFamily: "monospace", color: "#4A154B", fontWeight: 600 }}>chat:write</td>
                  <td style={{ padding: "14px 20px", color: "#64748b" }}>Bot</td>
                  <td style={{ padding: "14px 20px", color: "#334155" }}>To post AI search answers, citations, and interactive action buttons into the thread.</td>
                </tr>
                <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 20px", fontFamily: "monospace", color: "#4A154B", fontWeight: 600 }}>commands</td>
                  <td style={{ padding: "14px 20px", color: "#64748b" }}>Bot</td>
                  <td style={{ padding: "14px 20px", color: "#334155" }}>To enable slash commands like /gsearch for fast, private enterprise lookups.</td>
                </tr>
                <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "14px 20px", fontFamily: "monospace", color: "#4A154B", fontWeight: 600 }}>channels:read</td>
                  <td style={{ padding: "14px 20px", color: "#64748b" }}>Bot</td>
                  <td style={{ padding: "14px 20px", color: "#334155" }}>To identify public channels where the app has been invited to index and support discussions.</td>
                </tr>
                <tr>
                  <td style={{ padding: "14px 20px", fontFamily: "monospace", color: "#4A154B", fontWeight: 600 }}>im:history / im:write</td>
                  <td style={{ padding: "14px 20px", color: "#64748b" }}>Bot</td>
                  <td style={{ padding: "14px 20px", color: "#334155" }}>To allow teammates to message the bot directly in 1:1 private chats.</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Privacy Callout Box */}
          <div 
            style={{ 
              background: "linear-gradient(135deg, rgba(15, 181, 161, 0.08) 0%, rgba(74, 21, 75, 0.05) 100%)", 
              border: "1px solid #e2e8f0", 
              borderRadius: "14px", 
              padding: "24px 28px", 
              display: "flex", 
              gap: "20px", 
              alignItems: "center",
              flexWrap: "wrap",
              justifyContent: "space-between"
            }}
          >
            <div style={{ maxWidth: "680px" }}>
              <h4 style={{ fontSize: "17px", fontWeight: 700, color: "#14161f", marginBottom: "6px" }}>
                Complete Data Privacy Commitment
              </h4>
              <p style={{ fontSize: "14px", color: "#505767", lineHeight: 1.5, margin: 0 }}>
                We never store your raw messages for training third-party AI models. All data transmission is secured via TLS 1.3, and all vector indexes are encrypted at rest with AES-256. Review our full privacy practices anytime.
              </p>
            </div>
            <Link 
              href="/privacy-policy" 
              style={{ 
                background: "#ffffff", 
                color: "#0a8576", 
                padding: "10px 18px", 
                borderRadius: "8px", 
                fontWeight: 700, 
                fontSize: "14px", 
                border: "1px solid #0a8576",
                whiteSpace: "nowrap"
              }}
            >
              Read Privacy Policy →
            </Link>
          </div>
        </div>
      </section>

      {/* Frequently Asked Questions */}
      <section id="faq" style={{ padding: "72px 24px", background: "#ffffff", borderBottom: "1px solid #eef2f6" }}>
        <div style={{ maxWidth: "920px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "44px" }}>
            <h2 style={{ fontSize: "clamp(26px, 3.5vw, 36px)", fontWeight: 800, color: "#14161f", marginBottom: "14px" }}>
              Frequently Asked Questions
            </h2>
            <p style={{ fontSize: "16px", color: "#414856" }}>
              Everything you need to know about setting up and using GSearchAI with Slack.
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Does GSearchAI read all messages in every channel?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", lineHeight: 1.6, margin: 0 }}>
                No. GSearchAI only listens and responds in channels where it has been explicitly invited by an administrator or member, or when directly mentioned using <code>@GSearchAI</code> or slash commands. It does not monitor unsolicited background discussions.
              </p>
            </div>

            <div style={{ border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                How does GSearchAI know which documents to search?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", lineHeight: 1.6, margin: 0 }}>
                In your GSearchAI Dashboard, you configure your organization&apos;s data connectors (Google Drive, Notion, Confluence, Jira, etc.) and assign them to your workspace agent. The Slack integration connects to this agent, enabling queries across all connected knowledge bases with source citations.
              </p>
            </div>

            <div style={{ border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Can users see documents they don&apos;t have access to?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", lineHeight: 1.6, margin: 0 }}>
                No. GSearchAI enforces strict permission inheritance. Search results and synthesized answers only draw from documents and folders that the querying user has permission to access according to your source system&apos;s ACLs.
              </p>
            </div>

            <div style={{ border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", marginBottom: "8px" }}>
                Where can I get support if something goes wrong?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", lineHeight: 1.6, margin: 0 }}>
                Our customer engineering team is available to assist you. You can reach out anytime at{" "}
                <a href="mailto:gsearchai@gmail.com" style={{ color: "#0a8576", fontWeight: 600 }}>
                  gsearchai@gmail.com
                </a>
                .
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Final Installation CTA */}
      <section 
        style={{ 
          padding: "80px 24px", 
          background: "linear-gradient(135deg, #14161f 0%, #222529 100%)", 
          color: "#ffffff", 
          textAlign: "center" 
        }}
      >
        <div style={{ maxWidth: "800px", margin: "0 auto" }}>
          <div 
            style={{ 
              width: "60px", 
              height: "60px", 
              borderRadius: "16px", 
              background: "#4A154B", 
              margin: "0 auto 24px", 
              display: "flex", 
              alignItems: "center", 
              justifyContent: "center",
              fontSize: "28px" 
            }}
          >
            <FaSlack style={{ color: "#ffffff" }} />
          </div>

          <h2 style={{ fontSize: "clamp(28px, 4vw, 40px)", fontWeight: 800, color: "#ffffff", marginBottom: "16px" }}>
            Ready to empower your Slack workspace with GSearchAI?
          </h2>
          <p style={{ fontSize: "16px", color: "#9ca3af", maxWidth: "600px", margin: "0 auto 36px", lineHeight: 1.6 }}>
            Connect your team&apos;s knowledge bases in minutes. Zero manual tagging, instant verified citations, and enterprise-grade security.
          </p>

          <div style={{ display: "flex", justifyContent: "center", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
            <a 
              href={slackInstallUrl}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "transform 0.15s ease",
                height: "48px"
              }}
            >
              <img 
                alt="Add to Slack" 
                height="44" 
                width="153" 
                src="https://platform.slack-edge.com/img/add_to_slack.png" 
                srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x"
                style={{ borderRadius: "8px" }}
              />
            </a>

            <Link
              href="/dashboard/integrations"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                background: "#0fb5a1",
                color: "#ffffff",
                padding: "12px 24px",
                borderRadius: "10px",
                fontWeight: 700,
                fontSize: "15px"
              }}
            >
              <span>Manage in Dashboard</span>
              <FaArrowRight style={{ fontSize: "13px" }} />
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ background: "#ffffff", borderTop: "1px solid #eef2f6", padding: "40px 24px" }}>
        <div 
          style={{ 
            maxWidth: "1140px", 
            margin: "0 auto", 
            display: "flex", 
            flexWrap: "wrap", 
            justifyContent: "space-between", 
            alignItems: "center", 
            gap: "20px" 
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <BrandGlyph height={28} />
            <span style={{ fontSize: "13.5px", color: "#6b7280" }}>
              &copy; {new Date().getFullYear()} Gramosoft Private Limited. All rights reserved.
            </span>
          </div>

          <div style={{ display: "flex", gap: "24px", alignItems: "center", flexWrap: "wrap", fontSize: "14px" }}>
            <Link href="/privacy-policy" style={{ color: "#414856", fontWeight: 600 }}>
              Privacy Policy
            </Link>
            <Link href="/terms-of-service" style={{ color: "#414856", fontWeight: 600 }}>
              Terms of Service
            </Link>
            <Link href="/slack/success" style={{ color: "#414856", fontWeight: 600 }}>
              Installation Success Guide
            </Link>
            <Link href="/support" style={{ color: "#414856", fontWeight: 600 }}>
              App Support &amp; Help
            </Link>
          </div>
        </div>
      </footer>

      {/* Modal for Install via GSearchAI Guidance */}
      {isModalOpen && (
        <div 
          style={{ 
            position: "fixed", 
            inset: 0, 
            background: "rgba(0,0,0,0.5)", 
            display: "flex", 
            alignItems: "center", 
            justifyContent: "center", 
            zIndex: 999, 
            padding: "20px" 
          }}
          onClick={() => setIsModalOpen(false)}
        >
          <div 
            style={{ 
              background: "#ffffff", 
              borderRadius: "16px", 
              maxWidth: "520px", 
              width: "100%", 
              padding: "32px", 
              boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)" 
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
              <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "#4A154B", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <FaSlack style={{ color: "#fff", fontSize: "18px" }} />
              </div>
              <h3 style={{ fontSize: "20px", fontWeight: 700, margin: 0, color: "#14161f" }}>
                Install GSearchAI for Slack
              </h3>
            </div>

            <p style={{ fontSize: "14.5px", color: "#505767", lineHeight: 1.6, marginBottom: "20px" }}>
              Choose your preferred method to complete installation:
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginBottom: "24px" }}>
              <a
                href={slackInstallUrl}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "14px 16px",
                  borderRadius: "10px",
                  border: "1px solid #4A154B",
                  background: "rgba(74, 21, 75, 0.04)",
                  color: "#4A154B",
                  fontWeight: 700,
                  fontSize: "14.5px"
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <FaSlack />
                  <span>1-Click Direct Slack Authorization</span>
                </span>
                <FaArrowRight />
              </a>

              <Link
                href="/dashboard/integrations"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "14px 16px",
                  borderRadius: "10px",
                  border: "1px solid #e2e8f0",
                  background: "#f8fafc",
                  color: "#1e293b",
                  fontWeight: 600,
                  fontSize: "14.5px"
                }}
              >
                <span>Connect via GSearchAI Web Dashboard</span>
                <FaArrowRight style={{ color: "#94a3b8" }} />
              </Link>
            </div>

            <div style={{ textAlign: "right" }}>
              <button 
                onClick={() => setIsModalOpen(false)}
                style={{ 
                  background: "#f1f5f9", 
                  border: "none", 
                  padding: "8px 18px", 
                  borderRadius: "8px", 
                  fontWeight: 600, 
                  cursor: "pointer",
                  color: "#475569" 
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
