"use client";

import React, { useState } from "react";
import Link from "next/link";
import BrandGlyph from "@/app/components/landing/BrandGlyph";
import { 
  FaEnvelope, 
  FaClock, 
  FaSlack, 
  FaCircleCheck, 
  FaCircleQuestion, 
  FaShieldHalved, 
  FaArrowRight, 
  FaPaperPlane,
  FaHeadset,
  FaFileLines,
  FaRotateLeft
} from "react-icons/fa6";

export default function SupportPageContent() {
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    workspace: "",
    category: "Slack App Integration",
    subject: "",
    message: "",
  });
  const [loading, setLoading] = useState(false);
  const [submittedTicket, setSubmittedTicket] = useState<{ id: string } | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.email || !formData.message) {
      setErrorMsg("Please provide your email address and message.");
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await fetch("/api/support", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.error || "Failed to submit request.");
      }

      setSubmittedTicket({ id: data.ticketId || "GS-RECEIVED" });
    } catch (err: any) {
      console.error("Support form error:", err);
      setErrorMsg(err.message || "Failed to submit. Please email gsearchai@gmail.com directly.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ background: "#ffffff", color: "#14161f", minHeight: "100vh", fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif" }}>
      {/* Header */}
      <header style={{ borderBottom: "1px solid #eef2f6", background: "rgba(255,255,255,0.95)", position: "sticky", top: 0, zIndex: 50, backdropFilter: "blur(12px)" }}>
        <div style={{ maxWidth: "1140px", margin: "0 auto", padding: "16px 24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Link href="/" style={{ display: "flex", alignItems: "center" }}>
            <BrandGlyph height={34} />
          </Link>
          <div style={{ display: "flex", gap: "20px", alignItems: "center", fontSize: "14px" }}>
            <Link href="/slack" style={{ fontWeight: 600, color: "#4A154B", display: "flex", alignItems: "center", gap: "6px" }}>
              <FaSlack />
              <span>Slack App</span>
            </Link>
            <Link href="/privacy-policy" style={{ fontWeight: 600, color: "#414856" }}>
              Privacy Policy
            </Link>
            <Link 
              href="/login" 
              style={{ 
                background: "#0fb5a1", 
                color: "#ffffff", 
                padding: "8px 16px", 
                borderRadius: "8px", 
                fontWeight: 700 
              }}
            >
              Sign In
            </Link>
          </div>
        </div>
      </header>

      {/* Hero Banner */}
      <section 
        style={{ 
          background: "linear-gradient(135deg, rgba(15, 181, 161, 0.06) 0%, rgba(74, 21, 75, 0.05) 50%, #ffffff 100%)", 
          borderBottom: "1px solid #eef2f6", 
          padding: "54px 24px 60px",
          textAlign: "center"
        }}
      >
        <div style={{ maxWidth: "860px", margin: "0 auto" }}>
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
              marginBottom: "16px" 
            }}
          >
            <FaHeadset style={{ fontSize: "14px" }} />
            <span>Customer &amp; App Support</span>
            <span style={{ width: "4px", height: "4px", borderRadius: "50%", background: "#0a8576" }} />
            <span>Public Access</span>
          </div>

          <h1 style={{ fontSize: "clamp(28px, 4.5vw, 44px)", fontWeight: 800, color: "#14161f", letterSpacing: "-0.025em", marginBottom: "16px" }}>
            How can we help you?
          </h1>
          <p style={{ fontSize: "16.5px", color: "#475569", lineHeight: 1.6, maxWidth: "660px", margin: "0 auto 28px" }}>
            Get responsive assistance for GSearchAI and our Slack integration. <strong>No sign-in or account creation is required</strong> to contact our support team.
          </p>

          <div style={{ display: "flex", justifyContent: "center", gap: "24px", flexWrap: "wrap", fontSize: "13.5px", color: "#475569" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <FaCircleCheck style={{ color: "#0fb5a1" }} />
              <span><strong>No Account Needed:</strong> Direct email or webform</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <FaClock style={{ color: "#0fb5a1" }} />
              <span><strong>Guaranteed SLA:</strong> Response within 2 business days</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <FaShieldHalved style={{ color: "#0fb5a1" }} />
              <span><strong>Dedicated Slack Support:</strong> Integration assistance</span>
            </div>
          </div>
        </div>
      </section>

      {/* Main Support Grid: Contact Details & Interactive Form */}
      <section style={{ maxWidth: "1140px", margin: "0 auto", padding: "64px 24px 80px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "36px" }}>
          
          {/* Left Column: Direct Communication Channels & SLA */}
          <div>
            <h2 style={{ fontSize: "22px", fontWeight: 800, color: "#14161f", marginBottom: "8px" }}>
              Get in Touch with Our Team
            </h2>
            <p style={{ fontSize: "15px", color: "#64748b", lineHeight: 1.6, marginBottom: "28px" }}>
              Have questions about setting up GSearchAI in your Slack workspace, configuring document connectors, or managing permissions? Reach out directly using any channel below.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: "18px", marginBottom: "32px" }}>
              {/* Email Card 1 */}
              <div 
                style={{ 
                  background: "#f8fafc", 
                  border: "1px solid #e2e8f0", 
                  borderRadius: "14px", 
                  padding: "20px 24px" 
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                  <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "#e3f7f3", color: "#0a8576", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px" }}>
                    <FaEnvelope />
                  </div>
                  <div>
                    <div style={{ fontSize: "12px", textTransform: "uppercase", fontWeight: 700, color: "#64748b", letterSpacing: "0.05em" }}>
                      General &amp; Technical Support
                    </div>
                    <a href="mailto:gsearchai@gmail.com" style={{ fontSize: "16px", fontWeight: 700, color: "#0a8576", textDecoration: "none" }}>
                      gsearchai@gmail.com
                    </a>
                  </div>
                </div>
                <p style={{ fontSize: "13.5px", color: "#64748b", margin: 0 }}>
                  For general help, Slack bot troubleshooting, bug reports, and integration guidance.
                </p>
              </div>

              {/* Email Card 2 */}
              <div 
                style={{ 
                  background: "#f8fafc", 
                  border: "1px solid #e2e8f0", 
                  borderRadius: "14px", 
                  padding: "20px 24px" 
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
                  <div style={{ width: "36px", height: "36px", borderRadius: "8px", background: "rgba(74, 21, 75, 0.1)", color: "#4A154B", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px" }}>
                    <FaSlack />
                  </div>
                  <div>
                    <div style={{ fontSize: "12px", textTransform: "uppercase", fontWeight: 700, color: "#64748b", letterSpacing: "0.05em" }}>
                      Slack App &amp; Security Inquiries
                    </div>
                    <a href="mailto:gsearchai@gmail.com" style={{ fontSize: "16px", fontWeight: 700, color: "#4A154B", textDecoration: "none" }}>
                      gsearchai@gmail.com
                    </a>
                  </div>
                </div>
                <p style={{ fontSize: "13.5px", color: "#64748b", margin: 0 }}>
                  Assistance with Slack OAuth approvals, workspace installations, and data governance.
                </p>
              </div>

              {/* Response Time Notice */}
              <div 
                style={{ 
                  background: "#fffbeb", 
                  border: "1px solid #fef3c7", 
                  borderRadius: "12px", 
                  padding: "16px 20px" 
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#b45309", fontWeight: 700, fontSize: "14px", marginBottom: "4px" }}>
                  <FaClock />
                  <span>Support Responsiveness Commitment</span>
                </div>
                <p style={{ fontSize: "13px", color: "#78350f", margin: 0, lineHeight: 1.5 }}>
                  We respond to all customer tickets within <strong>2 business days</strong> (and typically within 2–4 hours during Monday through Friday, 9:00 AM – 6:00 PM IST/UTC).
                </p>
              </div>
            </div>

            {/* Quick Links */}
            <div>
              <div style={{ fontSize: "13px", fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "10px" }}>
                Helpful Documentation:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "14px" }}>
                <Link href="/slack" style={{ color: "#0a8576", fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>Slack App Installation Landing Page</span>
                  <FaArrowRight style={{ fontSize: "11px" }} />
                </Link>
                <Link href="/slack/success" style={{ color: "#0a8576", fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>Slack Post-Installation Guide &amp; Next Steps</span>
                  <FaArrowRight style={{ fontSize: "11px" }} />
                </Link>
                <Link href="/privacy-policy" style={{ color: "#0a8576", fontWeight: 600, display: "flex", alignItems: "center", gap: "6px" }}>
                  <span>Privacy Policy &amp; Third-Party Data Handling</span>
                  <FaArrowRight style={{ fontSize: "11px" }} />
                </Link>
              </div>
            </div>
          </div>

          {/* Right Column: Public Support Contact Form (No Login Required) */}
          <div 
            style={{ 
              background: "#ffffff", 
              border: "1px solid #e2e8f0", 
              borderRadius: "20px", 
              padding: "36px 32px", 
              boxShadow: "0 10px 30px -10px rgba(0,0,0,0.06)" 
            }}
          >
            {submittedTicket ? (
              <div style={{ textAlign: "center", padding: "40px 10px" }}>
                <div 
                  style={{ 
                    width: "64px", 
                    height: "64px", 
                    borderRadius: "50%", 
                    background: "#10b981", 
                    color: "#ffffff", 
                    display: "flex", 
                    alignItems: "center", 
                    justifyContent: "center", 
                    fontSize: "30px", 
                    margin: "0 auto 20px" 
                  }}
                >
                  <FaCircleCheck />
                </div>
                <h3 style={{ fontSize: "24px", fontWeight: 800, color: "#14161f", marginBottom: "10px" }}>
                  Support Ticket Received!
                </h3>
                <p style={{ fontSize: "15px", color: "#64748b", lineHeight: 1.6, maxWidth: "420px", margin: "0 auto 20px" }}>
                  Your request has been logged under ticket reference <strong>{submittedTicket.id}</strong>. A confirmation email has been sent, and an engineer will respond within <strong>2 business days</strong>.
                </p>
                <button
                  onClick={() => {
                    setSubmittedTicket(null);
                    setFormData({ name: "", email: "", workspace: "", category: "Slack App Integration", subject: "", message: "" });
                  }}
                  style={{
                    background: "#0fb5a1",
                    color: "#ffffff",
                    border: "none",
                    padding: "10px 22px",
                    borderRadius: "8px",
                    fontWeight: 700,
                    fontSize: "14px",
                    cursor: "pointer"
                  }}
                >
                  Submit Another Question
                </button>
              </div>
            ) : (
              <form onSubmit={handleSubmit}>
                <div style={{ marginBottom: "20px" }}>
                  <div style={{ display: "inline-block", background: "rgba(15, 181, 161, 0.1)", color: "#0a8576", fontSize: "11.5px", fontWeight: 800, textTransform: "uppercase", padding: "3px 8px", borderRadius: "4px", marginBottom: "6px" }}>
                    Public Support Webform
                  </div>
                  <h3 style={{ fontSize: "20px", fontWeight: 800, color: "#14161f", margin: "0 0 6px" }}>
                    Submit a Support Request
                  </h3>
                  <p style={{ fontSize: "13.5px", color: "#64748b", margin: 0 }}>
                    Fill out the form below. No login or existing account is required.
                  </p>
                </div>

                {errorMsg && (
                  <div style={{ background: "#fee2e2", border: "1px solid #fca5a5", color: "#991b1b", padding: "10px 14px", borderRadius: "8px", fontSize: "13.5px", marginBottom: "16px" }}>
                    {errorMsg}
                  </div>
                )}

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px", marginBottom: "14px" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                      Your Name
                    </label>
                    <input
                      type="text"
                      placeholder="Alex Smith"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none" }}
                    />
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                      Work Email <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="email"
                      required
                      placeholder="alex@company.com"
                      value={formData.email}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none" }}
                    />
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px", marginBottom: "14px" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                      Slack Workspace (Optional)
                    </label>
                    <input
                      type="text"
                      placeholder="acme-corp.slack.com"
                      value={formData.workspace}
                      onChange={(e) => setFormData({ ...formData, workspace: e.target.value })}
                      style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none" }}
                    />
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                      Category
                    </label>
                    <select
                      value={formData.category}
                      onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                      style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none", background: "#ffffff" }}
                    >
                      <option value="Slack App Integration">Slack App Integration</option>
                      <option value="Google Drive Connector">Google Drive Connector</option>
                      <option value="Search &amp; AI Accuracy">Search &amp; AI Accuracy</option>
                      <option value="Permissions &amp; Security">Permissions &amp; Security</option>
                      <option value="Data Deletion Request">Data Deletion Request (GDPR/CCPA)</option>
                      <option value="General Question">General Question</option>
                    </select>
                  </div>
                </div>

                <div style={{ marginBottom: "14px" }}>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                    Subject
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Issue inviting @GSearchAI to private channel"
                    value={formData.subject}
                    onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
                    style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none" }}
                  />
                </div>

                <div style={{ marginBottom: "20px" }}>
                  <label style={{ display: "block", fontSize: "13px", fontWeight: 700, color: "#334155", marginBottom: "6px" }}>
                    Describe your question or issue <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <textarea
                    required
                    rows={4}
                    placeholder="Please include details such as error messages, slash command used, or expected results..."
                    value={formData.message}
                    onChange={(e) => setFormData({ ...formData, message: e.target.value })}
                    style={{ width: "100%", padding: "10px 12px", border: "1px solid #cbd5e1", borderRadius: "8px", fontSize: "14px", outline: "none", resize: "vertical" }}
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "8px",
                    background: "#0fb5a1",
                    color: "#ffffff",
                    border: "none",
                    padding: "12px",
                    borderRadius: "10px",
                    fontWeight: 700,
                    fontSize: "15px",
                    cursor: loading ? "not-allowed" : "pointer",
                    boxShadow: "0 4px 12px rgba(15, 181, 161, 0.3)",
                    transition: "all 0.2s ease"
                  }}
                >
                  <FaPaperPlane style={{ fontSize: "13px" }} />
                  <span>{loading ? "Submitting Request..." : "Send Support Request"}</span>
                </button>
              </form>
            )}
          </div>
        </div>
      </section>

      {/* Common Slack Troubleshooting FAQ */}
      <section style={{ background: "#f8fafc", borderTop: "1px solid #eef2f6", padding: "64px 24px" }}>
        <div style={{ maxWidth: "860px", margin: "0 auto" }}>
          <div style={{ textAlign: "center", marginBottom: "36px" }}>
            <h2 style={{ fontSize: "24px", fontWeight: 800, color: "#14161f", marginBottom: "8px" }}>
              Frequently Asked Troubleshooting Questions
            </h2>
            <p style={{ fontSize: "15px", color: "#64748b", margin: 0 }}>
              Quick solutions to common questions when configuring the GSearchAI Slack app.
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                How do I add @GSearchAI to a private Slack channel?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", margin: 0, lineHeight: 1.6 }}>
                Open the private channel in Slack, type <code>/invite @GSearchAI</code>, and press Enter. The bot will join and can immediately answer questions whenever mentioned.
              </p>
            </div>

            <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                Why does Slack say &quot;This app isn&apos;t responding&quot;?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", margin: 0, lineHeight: 1.6 }}>
                Make sure your GSearchAI agent is linked to your Slack workspace in your dashboard. You can re-verify your connection under <strong>Integrations &gt; Slack</strong>. If the issue persists, send us a ticket above and our engineers will inspect your workspace endpoint.
              </p>
            </div>

            <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "20px 24px" }}>
              <h4 style={{ fontSize: "16px", fontWeight: 700, color: "#1e293b", margin: "0 0 6px" }}>
                How do I disconnect the Slack app or revoke permissions?
              </h4>
              <p style={{ fontSize: "14px", color: "#64748b", margin: 0, lineHeight: 1.6 }}>
                Workspace administrators can disconnect anytime in the GSearchAI Dashboard under <em>Integrations &gt; Slack &gt; Disconnect</em> or directly in Slack under <em>Manage Apps &gt; GSearchAI &gt; Remove App</em>.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ background: "#ffffff", borderTop: "1px solid #eef2f6", padding: "36px 24px" }}>
        <div style={{ maxWidth: "1140px", margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "16px", fontSize: "13.5px", color: "#64748b" }}>
          <div>
            &copy; {new Date().getFullYear()} Gramosoft Private Limited. All rights reserved.
          </div>
          <div style={{ display: "flex", gap: "20px" }}>
            <Link href="/slack" style={{ color: "#414856", fontWeight: 600 }}>Slack App</Link>
            <Link href="/privacy-policy" style={{ color: "#414856", fontWeight: 600 }}>Privacy Policy</Link>
            <Link href="/terms-of-service" style={{ color: "#414856", fontWeight: 600 }}>Terms of Service</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
