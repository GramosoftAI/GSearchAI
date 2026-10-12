"use client";

import React from "react";
import Link from "next/link";
import { 
  FaShieldHalved, 
  FaSlack, 
  FaEnvelope, 
  FaServer 
} from "react-icons/fa6";

export default function SecurityPolicy() {
  return (
    <div 
      className="security-policy-container" 
      style={{ 
        background: "var(--bg, #ffffff)", 
        color: "var(--body, #414856)", 
        minHeight: "80vh",
        padding: "48px 20px 80px",
        fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif"
      }}
    >
      <div style={{ maxWidth: "960px", margin: "0 auto" }}>
        
        {/* Header Title & Date Badges */}
        <div 
          style={{ 
            background: "linear-gradient(135deg, rgba(15, 181, 161, 0.06) 0%, rgba(74, 21, 75, 0.06) 50%, rgba(124, 108, 240, 0.05) 100%)",
            border: "1px solid var(--line, #e5e9ef)",
            borderRadius: "20px",
            padding: "40px 28px",
            textAlign: "center",
            marginBottom: "36px"
          }}
        >
          <div 
            style={{ 
              display: "inline-flex", 
              alignItems: "center", 
              gap: "6px", 
              padding: "4px 14px", 
              marginBottom: "16px", 
              borderRadius: "9999px", 
              fontWeight: 700, 
              textTransform: "uppercase", 
              background: "var(--teal-soft, #e3f7f3)", 
              color: "var(--teal-deep, #0a8576)", 
              fontSize: "12px", 
              letterSpacing: "0.05em" 
            }}
          >
            <FaShieldHalved />
            <span>Security &amp; Vulnerability Disclosure</span>
          </div>

          <h1 
            style={{ 
              color: "var(--ink, #14161f)", 
              fontSize: "clamp(28px, 4vw, 42px)", 
              fontWeight: 800, 
              letterSpacing: "-0.025em",
              marginBottom: "16px",
              lineHeight: 1.15
            }}
          >
            Vulnerability Disclosure Program (VDP)
          </h1>

          <p 
            style={{ 
              maxWidth: "760px", 
              margin: "0 auto 24px", 
              fontSize: "16.5px", 
              color: "var(--muted, #6b7280)",
              lineHeight: 1.6
            }}
          >
            At GSearchAI, security and customer data protection are paramount. Our Vulnerability Disclosure Program provides clear guidelines for security researchers and customers to conduct responsible vulnerability research and disclose security issues across our platform and integrations, including our <strong>Slack App</strong>.
          </p>
          
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "10px", fontSize: "13px" }}>
            <span 
              style={{ 
                background: "#ffffff", 
                color: "var(--ink, #14161f)", 
                border: "1px solid var(--line, #e5e9ef)", 
                padding: "6px 16px", 
                borderRadius: "9999px", 
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)"
              }}
            >
              <strong>Status:</strong> Active &amp; Monitored
            </span>
            <span 
              style={{ 
                background: "#ffffff", 
                color: "var(--ink, #14161f)", 
                border: "1px solid var(--line, #e5e9ef)", 
                padding: "6px 16px", 
                borderRadius: "9999px", 
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)"
              }}
            >
              <strong>Security Contact:</strong> gsearchai@gmail.com
            </span>
            <span 
              style={{ 
                background: "#ffffff", 
                color: "var(--ink, #14161f)", 
                border: "1px solid var(--line, #e5e9ef)", 
                padding: "6px 16px", 
                borderRadius: "9999px", 
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)"
              }}
            >
              <strong>Operated by:</strong> Gramosoft Private Limited
            </span>
          </div>
        </div>

        {/* Slack App In-Scope Highlight Banner */}
        <div 
          style={{ 
            background: "linear-gradient(135deg, rgba(74, 21, 75, 0.06) 0%, rgba(15, 181, 161, 0.08) 100%)", 
            border: "2px solid #4A154B", 
            borderRadius: "16px", 
            padding: "24px 28px", 
            marginBottom: "32px",
            boxShadow: "0 4px 16px rgba(74, 21, 75, 0.08)"
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "8px" }}>
            <div style={{ width: "32px", height: "32px", borderRadius: "8px", background: "#4A154B", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <FaSlack />
            </div>
            <h3 style={{ color: "#4A154B", fontSize: "18px", fontWeight: 800, margin: 0 }}>
              Does our Vulnerability Disclosure Program cover our Slack App?
            </h3>
          </div>
          <p style={{ fontSize: "15px", color: "#1e293b", margin: "8px 0 0", lineHeight: 1.6 }}>
            <strong>Yes, absolutely.</strong> The GSearchAI Vulnerability Disclosure Program explicitly covers our Slack application, including all Slack bot endpoints, event subscriptions, slash command handlers (<code>/gsearch</code>), interactive Block Kit components, OAuth 2.0 authorization flows, and backend knowledge retrieval connectors.
          </p>
        </div>

        {/* Main Content Sections */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px", fontSize: "15.5px", lineHeight: "1.7" }}>
          
          {/* Section 1: Scope */}
          <section 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              1. Program Scope
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              The following properties and integrations are in scope for our Vulnerability Disclosure Program:
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "14px", marginBottom: "14px" }}>
              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#4A154B", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  <FaSlack />
                  <span>Slack Application &amp; Bot Endpoints</span>
                </div>
                <p style={{ fontSize: "13.5px", color: "#64748b", margin: 0 }}>
                  Bot mentions (<code>@GSearchAI</code>), slash commands, Slack OAuth redirects, event webhook receivers, and interactive block actions.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  <FaServer />
                  <span>GSearchAI Web Platform &amp; APIs</span>
                </div>
                <p style={{ fontSize: "13.5px", color: "#64748b", margin: 0 }}>
                  Web application dashboard (<code>https://gsearchai.com</code>), user authentication, API endpoints, and database knowledge connectors.
                </p>
              </div>
            </div>

            <h4 style={{ fontSize: "15px", fontWeight: 700, color: "#14161f", marginBottom: "8px" }}>Out of Scope:</h4>
            <ul style={{ paddingLeft: "20px", margin: 0, fontSize: "14px", color: "#64748b" }}>
              <li>Distributed Denial of Service (DDoS/DoS) attacks against our infrastructure.</li>
              <li>Spam, phishing, or social engineering attacks targeting employees or customers.</li>
              <li>Physical security attacks against facilities or data centers.</li>
              <li>Third-party services or infrastructure not directly operated by Gramosoft Private Limited.</li>
            </ul>
          </section>

          {/* Section 2: Reporting Guidelines */}
          <section 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              2. How to Report a Vulnerability
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              If you identify a security flaw or potential vulnerability in our Slack app or platform, please submit your findings directly to our security engineering team:
            </p>

            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "12px", padding: "20px", marginBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "10px", flexWrap: "wrap" }}>
                <FaEnvelope style={{ color: "#0fb5a1", fontSize: "18px" }} />
                <span style={{ fontSize: "15px", fontWeight: 700, color: "#1e293b" }}>Dedicated Security Reporting Email:</span>
                <a href="mailto:gsearchai@gmail.com" style={{ fontSize: "15px", fontWeight: 700, color: "#0fb5a1", textDecoration: "underline" }}>
                  gsearchai@gmail.com
                </a>
              </div>
              <p style={{ fontSize: "13.5px", color: "#64748b", margin: "0 0 10px", lineHeight: 1.5 }}>
                You can also submit security reports through our public <Link href="/support" style={{ color: "#0a8576", fontWeight: 600 }}>Support &amp; Help Portal</Link> without needing to create an account.
              </p>
              <div style={{ fontSize: "13.5px", color: "#334155" }}>
                <strong>Please include in your report:</strong>
                <ul style={{ paddingLeft: "18px", margin: "6px 0 0" }}>
                  <li>Clear description and severity of the vulnerability.</li>
                  <li>Step-by-step reproduction steps or proof-of-concept (PoC).</li>
                  <li>Affected URL, Slack endpoint, or component.</li>
                  <li>Any potential impact or risk assessment.</li>
                </ul>
              </div>
            </div>
          </section>

          {/* Section 3: SLA & Response Commitments */}
          <section 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              3. Response &amp; Remediation SLA
            </h2>
            <p style={{ marginTop: 0, marginBottom: "14px" }}>
              Our security team is committed to timely triage, communication, and resolution:
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "14px", marginBottom: "12px" }}>
              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "4px" }}>
                  Initial Acknowledgment
                </div>
                <div style={{ fontSize: "20px", fontWeight: 800, color: "#14161f", marginBottom: "4px" }}>
                  Within 24–48 hours
                </div>
                <p style={{ fontSize: "13px", color: "#64748b", margin: 0 }}>
                  We confirm receipt of your report and assign a security triage engineer.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "4px" }}>
                  Triage &amp; Assessment
                </div>
                <div style={{ fontSize: "20px", fontWeight: 800, color: "#14161f", marginBottom: "4px" }}>
                  Within 72 hours
                </div>
                <p style={{ fontSize: "13px", color: "#64748b", margin: 0 }}>
                  We validate the vulnerability and determine the severity rating.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "4px" }}>
                  Remediation &amp; Patching
                </div>
                <div style={{ fontSize: "20px", fontWeight: 800, color: "#14161f", marginBottom: "4px" }}>
                  7 to 14 days
                </div>
                <p style={{ fontSize: "13px", color: "#64748b", margin: 0 }}>
                  Critical vulnerabilities patched within 7 business days, high within 14 business days.
                </p>
              </div>
            </div>
          </section>

          {/* Section 4: Safe Harbor Commitment */}
          <section 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              4. Safe Harbor Guarantee
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              We consider security research conducted in accordance with this policy to be authorized. Gramosoft Private Limited will not pursue civil action or initiate legal complaints against researchers who:
            </p>
            <ul style={{ paddingLeft: "20px", margin: "0 0 14px", fontSize: "14.5px" }}>
              <li style={{ marginBottom: "6px" }}>Act in good faith to identify vulnerabilities without causing disruption to services or systems.</li>
              <li style={{ marginBottom: "6px" }}>Do not view, alter, extract, delete, or destroy customer or organizational data.</li>
              <li style={{ marginBottom: "6px" }}>Provide us reasonable time to remediate the vulnerability prior to public disclosure.</li>
              <li>Comply with applicable local, state, and international laws.</li>
            </ul>
          </section>

          {/* Contact Footer Box */}
          <div 
            style={{ 
              background: "linear-gradient(135deg, #14161f 0%, #1e212f 100%)", 
              borderRadius: "16px", 
              padding: "28px 32px", 
              color: "#ffffff",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "20px"
            }}
          >
            <div>
              <h3 style={{ fontSize: "18px", fontWeight: 700, margin: "0 0 6px", color: "#ffffff" }}>
                Questions regarding our Security &amp; VDP?
              </h3>
              <p style={{ fontSize: "14px", color: "rgba(255,255,255,0.75)", margin: 0 }}>
                Reach our team directly at <a href="mailto:gsearchai@gmail.com" style={{ color: "#2dd4bf", fontWeight: 600 }}>gsearchai@gmail.com</a>
              </p>
            </div>
            <div style={{ display: "flex", gap: "12px" }}>
              <Link 
                href="/slack" 
                style={{ 
                  background: "rgba(255,255,255,0.1)", 
                  color: "#ffffff", 
                  padding: "10px 18px", 
                  borderRadius: "8px", 
                  fontWeight: 600, 
                  fontSize: "14px",
                  border: "1px solid rgba(255,255,255,0.2)"
                }}
              >
                Slack App Page
              </Link>
              <Link 
                href="/privacy-policy" 
                style={{ 
                  background: "#0fb5a1", 
                  color: "#ffffff", 
                  padding: "10px 18px", 
                  borderRadius: "8px", 
                  fontWeight: 700, 
                  fontSize: "14px"
                }}
              >
                Privacy Policy
              </Link>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
