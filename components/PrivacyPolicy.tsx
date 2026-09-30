import React from "react";

export default function PrivacyPolicy() {
  return (
    <div 
      className="privacy-policy-container" 
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
            background: "linear-gradient(135deg, rgba(15, 181, 161, 0.05) 0%, rgba(74, 21, 75, 0.05) 50%, rgba(124, 108, 240, 0.05) 100%)",
            border: "1px solid var(--line, #e5e9ef)",
            borderRadius: "20px",
            padding: "40px 28px",
            textAlign: "center",
            marginBottom: "32px"
          }}
        >
          <div 
            style={{ 
              display: "inline-block", 
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
            Legal &amp; Privacy Compliance
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
            GSearchAI Privacy Policy
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
            This Privacy Policy details how GSearchAI collects, uses, processes, stores, and protects data when using the GSearchAI platform and third-party integrations, including our <strong>Slack App</strong> and <strong>Google Drive connector</strong>.
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
              <strong>Effective Date:</strong> September 4, 2026
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
              <strong>Last Updated:</strong> September 30, 2026
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

        {/* Quick Jump Anchors for Compliance Reviewers */}
        <div 
          style={{ 
            background: "#f8fafc", 
            border: "1px solid #e2e8f0", 
            borderRadius: "14px", 
            padding: "16px 20px", 
            marginBottom: "32px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "12px",
            fontSize: "13.5px"
          }}
        >
          <span style={{ fontWeight: 700, color: "#1e293b" }}>Quick Navigation:</span>
          <div style={{ display: "flex", gap: "14px", flexWrap: "wrap" }}>
            <a href="#section-slack" style={{ color: "#4A154B", fontWeight: 700, textDecoration: "underline" }}>
              Slack Data Policy
            </a>
            <a href="#section-google" style={{ color: "#0a8576", fontWeight: 700, textDecoration: "underline" }}>
              Google Drive Data Policy
            </a>
            <a href="#section-passthrough" style={{ color: "#7c6cf0", fontWeight: 700, textDecoration: "underline" }}>
              Passthrough Data Disclosure
            </a>
            <a href="#section-retention" style={{ color: "#0284c7", fontWeight: 700, textDecoration: "underline" }}>
              Retention &amp; Deletion
            </a>
            <a href="#section-contact" style={{ color: "#14161f", fontWeight: 700, textDecoration: "underline" }}>
              Contact &amp; Requests
            </a>
          </div>
        </div>

        {/* Policy Content Sections */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px", fontSize: "15.5px", lineHeight: "1.7" }}>
          
          {/* Section 1: Introduction */}
          <section 
            id="section-1" 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              1. Introduction &amp; Scope
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              GSearchAI (a product operated by Gramosoft Private Limited) is an enterprise AI search and knowledge intelligence platform. Our platform enables organizations to index, query, analyze, and retrieve information across their connected workplace tools and databases using natural language.
            </p>
            <p style={{ marginBottom: "12px" }}>
              This Privacy Policy applies to all individuals and organizations that interact with our website, software platform, web dashboard, APIs, and connected third-party integrations, specifically including the <strong>GSearchAI Slack Application</strong> and <strong>Google Drive Connector</strong>.
            </p>
            <p style={{ marginBottom: 0 }}>
              We are committed to maintaining the highest level of privacy and data security. We do not sell your personal data or your organization&apos;s data, and we do not use your proprietary documents or chat discussions to train generalized or public AI models.
            </p>
          </section>

          {/* Section 2: SLACK INTEGRATION & THIRD-PARTY WORKPLACE DATA POLICY */}
          <section 
            id="section-slack" 
            style={{ 
              background: "#ffffff", 
              border: "2px solid #4A154B", 
              borderRadius: "16px", 
              padding: "32px",
              boxShadow: "0 6px 24px -8px rgba(74, 21, 75, 0.15)"
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "12px" }}>
              <span style={{ background: "#4A154B", color: "#ffffff", padding: "4px 10px", borderRadius: "6px", fontSize: "12px", fontWeight: 800, textTransform: "uppercase" }}>
                Slack Marketplace Policy
              </span>
              <span style={{ fontSize: "14px", color: "#64748b", fontWeight: 600 }}>Third-Party Workplace Data Handling</span>
            </div>

            <h2 style={{ color: "#4A154B", fontSize: "22px", fontWeight: 800, marginTop: 0, marginBottom: "16px" }}>
              2. Slack App Data Handling, Collection &amp; Use
            </h2>
            <p style={{ marginTop: 0, marginBottom: "14px" }}>
              When your workspace administrator installs the GSearchAI app to a Slack workspace or when team members interact with the app in Slack, GSearchAI receives and processes limited third-party data required to provide the search and assistance service.
            </p>

            {/* A: What data is collected from Slack */}
            <div style={{ marginBottom: "20px" }}>
              <h3 style={{ color: "var(--ink, #14161f)", fontSize: "17px", fontWeight: 700, marginBottom: "8px" }}>
                A. What Data is Collected from Slack
              </h3>
              <p style={{ fontSize: "14.5px", color: "var(--body, #414856)", marginBottom: "10px" }}>
                GSearchAI only collects information strictly necessary to authenticate your workspace, verify authorizations, and execute AI search queries:
              </p>
              <ul style={{ paddingLeft: "20px", margin: 0, fontSize: "14.5px", color: "var(--body, #414856)" }}>
                <li style={{ marginBottom: "6px" }}>
                  <strong>Workspace &amp; Team Identifiers:</strong> Slack Team ID (<code>team_id</code>), Team Name, and Team Domain to route queries to your organization&apos;s designated agent and knowledge base.
                </li>
                <li style={{ marginBottom: "6px" }}>
                  <strong>Channel Metadata:</strong> Channel ID and Channel Name for public or private channels where the bot has been explicitly invited (via <code>/invite @GSearchAI</code>) or selected in the integration configuration.
                </li>
                <li style={{ marginBottom: "6px" }}>
                  <strong>User Identifiers:</strong> Slack User ID (<code>user_id</code>) and Username of the person invoking a search or sending a prompt, used to verify role-based access permissions and respond in thread context.
                </li>
                <li style={{ marginBottom: "6px" }}>
                  <strong>Query &amp; Prompt Content:</strong> The text content of messages explicitly addressed to <code>@GSearchAI</code>, direct messages sent to the bot, or search terms entered through the <code>/gsearch</code> slash command.
                </li>
                <li>
                  <strong>OAuth Credentials:</strong> Encrypted bot access tokens provided by Slack during the OAuth 2.0 installation flow, stored with AES-256 encryption.
                </li>
              </ul>
            </div>

            {/* B: How data collected from Slack is used */}
            <div style={{ marginBottom: "20px" }}>
              <h3 style={{ color: "var(--ink, #14161f)", fontSize: "17px", fontWeight: 700, marginBottom: "8px" }}>
                B. How the Collected Data is Used
              </h3>
              <p style={{ fontSize: "14.5px", color: "var(--body, #414856)", marginBottom: "8px" }}>
                Data collected from Slack is used exclusively to:
              </p>
              <ul style={{ paddingLeft: "20px", margin: 0, fontSize: "14.5px" }}>
                <li style={{ marginBottom: "6px" }}>Authenticate and route requests between Slack and your configured GSearchAI knowledge agent.</li>
                <li style={{ marginBottom: "6px" }}>Perform semantic vector search across your authorized connectors (e.g., Google Drive, Confluence, Jira, Notion) matching the user&apos;s query.</li>
                <li style={{ marginBottom: "6px" }}>Generate concise, citation-backed answers with verifiable document links and post them back into the Slack channel, thread, or direct message via Slack Block Kit.</li>
                <li>Enforce permission boundaries so users only see search results from documents they are authorized to access.</li>
              </ul>
            </div>

            {/* C: Strict Prohibition on Model Training */}
            <div 
              style={{ 
                background: "rgba(74, 21, 75, 0.05)", 
                border: "1px solid rgba(74, 21, 75, 0.2)", 
                borderRadius: "10px", 
                padding: "16px 20px", 
                marginBottom: "20px" 
              }}
            >
              <h4 style={{ color: "#4A154B", fontSize: "15px", fontWeight: 700, margin: "0 0 6px" }}>
                Zero AI / LLM Model Training Guarantee
              </h4>
              <p style={{ fontSize: "14px", color: "#14161f", margin: 0, lineHeight: 1.6 }}>
                GSearchAI <strong>never</strong> uses Slack messages, user prompts, channel discussions, or returned search results to train, fine-tune, or evaluate generalized foundation or third-party artificial intelligence models. Your data remains strictly private to your tenant.
              </p>
            </div>
          </section>

          {/* Section 3: PASSTHROUGH & TECHNICAL LOGGING DISCLOSURE */}
          <section 
            id="section-passthrough" 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              3. Data Received But Not Used (Passthrough &amp; System Logging)
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              When interacting with third-party APIs such as Slack or Google, our web servers receive standard protocol payloads and technical metadata that pass through our infrastructure.
            </p>
            
            <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "18px", marginBottom: "16px" }}>
              <h3 style={{ fontSize: "15px", fontWeight: 700, color: "#1e293b", marginTop: 0, marginBottom: "8px" }}>
                Passthrough Payloads &amp; Metadata Received:
              </h3>
              <p style={{ fontSize: "14px", color: "#475569", margin: "0 0 10px", lineHeight: 1.6 }}>
                Slack slash command payloads, interactive Block Kit actions, and webhook events inherently include auxiliary parameters such as <code>trigger_id</code>, <code>response_url</code>, <code>api_app_id</code>, <code>enterprise_id</code>, internal request timestamps, IP addresses, and HTTP user-agent headers.
              </p>
              <h4 style={{ fontSize: "14px", fontWeight: 700, color: "#0f172a", margin: "0 0 6px" }}>
                Our Explicit Commitment Regarding Unused Data:
              </h4>
              <p style={{ fontSize: "14px", color: "#334155", margin: 0, lineHeight: 1.6 }}>
                While this technical data passes through our services during standard HTTPS transmission, <strong>GSearchAI does not store, profile, track, aggregate, or monetize this auxiliary information</strong>. It is processed ephemerally in active memory solely to complete the immediate Slack API request cycle. Technical system logs maintained for server performance and cybersecurity are stripped of sensitive message content and automatically overwritten on a rolling 30-day schedule.
              </p>
            </div>
          </section>

          {/* Section 4: GOOGLE DRIVE USER DATA POLICY (Full Limited Use Disclosure) */}
          <section 
            id="section-google" 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <div 
              style={{ 
                background: "var(--teal-soft, #e3f7f3)", 
                border: "1.5px solid rgba(15, 181, 161, 0.3)", 
                borderRadius: "12px",
                padding: "20px 24px",
                marginBottom: "24px"
              }}
            >
              <h3 
                style={{ 
                  color: "var(--teal-deep, #0a8576)", 
                  fontSize: "17px", 
                  fontWeight: 700, 
                  marginTop: 0,
                  marginBottom: "8px" 
                }}
              >
                Google API Services User Data Policy Compliance
              </h3>
              <p style={{ fontSize: "14.5px", lineHeight: "1.6", color: "var(--ink, #14161f)", margin: 0 }}>
                GSearchAI&apos;s use and transfer to any other app of information received from Google APIs adheres to the{" "}
                <a 
                  href="https://developers.google.com/terms/api-services-user-data-policy" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  style={{ color: "var(--teal-deep, #0a8576)", fontWeight: 700, textDecoration: "underline" }}
                >
                  Google API Services User Data Policy
                </a>
                , including the Limited Use requirements.
              </p>
            </div>

            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              4. Google Drive Data Access, Storage &amp; Protection
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              When you connect Google Drive to GSearchAI, our platform accesses file metadata (file names, IDs, MIME types, timestamps) and document content (Google Docs, PDFs, Word, Excel, CSV files) only for files you explicitly select or make available for indexing.
            </p>
            <ul style={{ paddingLeft: "20px", margin: "0 0 16px", fontSize: "14.5px" }}>
              <li style={{ marginBottom: "6px" }}><strong>GSearchAI does not sell Google user data.</strong></li>
              <li style={{ marginBottom: "6px" }}><strong>GSearchAI does not use Google user data to train, fine-tune, or develop generalized AI/ML models.</strong></li>
              <li><strong>OAuth tokens are protected with AES-256 encryption and TLS 1.3 transmission.</strong></li>
            </ul>
          </section>

          {/* Section 5: DATA RETENTION TIMELINES */}
          <section 
            id="section-retention" 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              5. How Long Data is Kept (Data Retention Timelines)
            </h2>
            <p style={{ marginTop: 0, marginBottom: "14px" }}>
              We apply strict data minimization principles to ensure information is retained only as long as necessary to provide the services requested:
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "16px", marginBottom: "16px" }}>
              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  Chat &amp; Search Queries
                </div>
                <p style={{ fontSize: "13.5px", color: "#475569", margin: 0, lineHeight: 1.5 }}>
                  Slack queries and generated answers are held ephemerally in active memory during processing and are not stored in permanent log databases for model mining.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  Knowledge Base Indexes
                </div>
                <p style={{ fontSize: "13.5px", color: "#475569", margin: 0, lineHeight: 1.5 }}>
                  Vector embeddings and document chunks are retained only for the active lifespan of the associated GSearchAI workspace or customer account.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  OAuth Credentials &amp; Tokens
                </div>
                <p style={{ fontSize: "13.5px", color: "#475569", margin: 0, lineHeight: 1.5 }}>
                  Stored encrypted for the duration of the integration. Immediately revoked and purged when an admin disconnects the Slack app or Google Drive integration.
                </p>
              </div>

              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "16px" }}>
                <div style={{ color: "#0a8576", fontWeight: 700, fontSize: "14px", marginBottom: "6px" }}>
                  Technical Diagnostic Logs
                </div>
                <p style={{ fontSize: "13.5px", color: "#475569", margin: 0, lineHeight: 1.5 }}>
                  System diagnostic logs and HTTP error codes are automatically purged on a rolling 30-day lifecycle.
                </p>
              </div>
            </div>
          </section>

          {/* Section 6: ACCESS, TRANSFER, AND DELETION RIGHTS (GDPR / CCPA) */}
          <section 
            id="section-rights" 
            style={{ 
              background: "#ffffff", 
              border: "1px solid var(--line, #e5e9ef)", 
              borderRadius: "16px", 
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)"
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              6. How an Individual Can Request Access, Transfer, or Deletion of Data
            </h2>
            <p style={{ marginTop: 0, marginBottom: "14px" }}>
              Regardless of your geographic location, GSearchAI honors global privacy principles aligned with the <strong>European General Data Protection Regulation (GDPR)</strong>, the <strong>California Consumer Privacy Act (CCPA/CPRA)</strong>, and applicable national privacy statutes.
            </p>

            <h3 style={{ fontSize: "16px", fontWeight: 700, color: "var(--ink, #14161f)", marginBottom: "8px" }}>
              Your Data Privacy Rights Include:
            </h3>
            <ul style={{ paddingLeft: "20px", margin: "0 0 16px", fontSize: "14.5px" }}>
              <li style={{ marginBottom: "6px" }}>
                <strong>Right to Access:</strong> You can request a confirmation of whether we process your data and receive a copy of your personal data.
              </li>
              <li style={{ marginBottom: "6px" }}>
                <strong>Right to Data Portability (Transfer):</strong> You can request to receive your stored data in a structured, commonly used, and machine-readable format (JSON or CSV).
              </li>
              <li style={{ marginBottom: "6px" }}>
                <strong>Right to Deletion / Erasure:</strong> You can request complete erasure of your account, indexed documents, chat interactions, vector embeddings, and OAuth tokens from our servers.
              </li>
              <li style={{ marginBottom: "6px" }}>
                <strong>Right to Disconnect:</strong> You can revoke third-party app access at any time through self-service dashboards.
              </li>
            </ul>

            <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: "10px", padding: "16px 20px", marginBottom: "16px" }}>
              <h4 style={{ color: "#166534", fontSize: "15px", fontWeight: 700, margin: "0 0 6px" }}>
                Immediate Self-Service Disconnection:
              </h4>
              <p style={{ fontSize: "14px", color: "#14532d", margin: 0, lineHeight: 1.6 }}>
                <strong>For Slack:</strong> Administrators can remove the app directly via your Slack workspace settings (<em>Slack &gt; Manage Apps &gt; GSearchAI &gt; Remove App</em>) or in the GSearchAI Dashboard under <em>Integrations &gt; Slack &gt; Disconnect</em>. This immediately invalidates the bot token.
                <br />
                <strong>For Google Drive:</strong> Disconnect in the GSearchAI Dashboard or via your Google Account permissions page at <a href="https://myaccount.google.com/permissions" target="_blank" rel="noopener noreferrer" style={{ color: "#166534", fontWeight: 700, textDecoration: "underline" }}>myaccount.google.com/permissions</a>.
              </p>
            </div>
          </section>

          {/* Section 7: CONTACT INFORMATION FOR DATA REQUESTS */}
          <section 
            id="section-contact" 
            style={{ 
              background: "linear-gradient(135deg, #14161f 0%, #1e212f 100%)", 
              border: "1px solid var(--line-2, #d9dfe8)", 
              borderRadius: "16px", 
              padding: "32px",
              color: "#ffffff"
            }}
          >
            <h2 style={{ color: "#ffffff", fontSize: "22px", fontWeight: 800, marginTop: 0, marginBottom: "12px" }}>
              7. How to Contact Us to Exercise Your Data Rights
            </h2>
            <p style={{ fontSize: "15px", color: "rgba(255,255,255,0.85)", margin: "0 0 24px", lineHeight: 1.6 }}>
              To submit a formal request to access, download, transfer, or permanently delete your data, please use any of our electronic communication channels below. We verify each request to protect your security and respond within <strong>30 calendar days</strong> (or 48 hours for immediate disconnection confirmations).
            </p>
            
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "16px", marginBottom: "24px" }}>
              <div style={{ background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "12px", padding: "18px" }}>
                <span style={{ display: "block", textTransform: "uppercase", fontSize: "11px", fontWeight: 700, color: "#2dd4bf", marginBottom: "6px" }}>
                  Primary Privacy Email
                </span>
                <a href="mailto:privacy@gsearchai.com" style={{ color: "#ffffff", fontWeight: 700, fontSize: "16px", textDecoration: "none" }}>
                  privacy@gsearchai.com
                </a>
                <p style={{ margin: "6px 0 0", fontSize: "12.5px", color: "rgba(255,255,255,0.65)" }}>
                  Monitored directly by our Data Protection Officer (DPO).
                </p>
              </div>
              
              <div style={{ background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "12px", padding: "18px" }}>
                <span style={{ display: "block", textTransform: "uppercase", fontSize: "11px", fontWeight: 700, color: "#2dd4bf", marginBottom: "6px" }}>
                  Support &amp; Deletion Inquiries
                </span>
                <a href="mailto:gsearchai@gmail.com" style={{ color: "#ffffff", fontWeight: 700, fontSize: "16px", textDecoration: "none" }}>
                  gsearchai@gmail.com
                </a>
                <p style={{ margin: "6px 0 0", fontSize: "12.5px", color: "rgba(255,255,255,0.65)" }}>
                  General customer care &amp; integration assistance.
                </p>
              </div>

              <div style={{ background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: "12px", padding: "18px" }}>
                <span style={{ display: "block", textTransform: "uppercase", fontSize: "11px", fontWeight: 700, color: "#2dd4bf", marginBottom: "6px" }}>
                  Online Privacy Request Webform
                </span>
                <a href="https://gsearchai.com" target="_blank" rel="noopener noreferrer" style={{ color: "#ffffff", fontWeight: 700, fontSize: "16px", textDecoration: "none" }}>
                  gsearchai.com/privacy-policy &rarr;
                </a>
                <p style={{ margin: "6px 0 0", fontSize: "12.5px", color: "rgba(255,255,255,0.65)" }}>
                  Submit data requests directly via our web portal.
                </p>
              </div>
            </div>

            <div style={{ borderTop: "1px solid rgba(255,255,255,0.15)", paddingTop: "18px", fontSize: "13.5px", color: "rgba(255,255,255,0.7)" }}>
              <strong>Operating Entity:</strong> Gramosoft Private Limited &bull; Legal Compliance Office &bull; Website: <a href="https://gsearchai.com" style={{ color: "#ffffff" }}>https://gsearchai.com</a>
            </div>
          </section>

        </div>
      </div>
    </div>
  );
}
