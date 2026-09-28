import React from "react";

export default function TermsOfService() {
  return (
    <div
      className="terms-of-service-container"
      style={{
        background: "var(--bg, #ffffff)",
        color: "var(--body, #414856)",
        minHeight: "80vh",
        padding: "48px 20px 80px",
        fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif",
      }}
    >
      <div style={{ maxWidth: "920px", margin: "0 auto" }}>
        {/* Header Title & Date Badges */}
        <div
          style={{
            background:
              "linear-gradient(135deg, rgba(15, 181, 161, 0.05) 0%, rgba(124, 108, 240, 0.05) 100%)",
            border: "1px solid var(--line, #e5e9ef)",
            borderRadius: "20px",
            padding: "40px 28px",
            textAlign: "center",
            marginBottom: "32px",
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
              letterSpacing: "0.05em",
            }}
          >
            Legal &amp; Agreement
          </div>
          <h1
            style={{
              color: "var(--ink, #14161f)",
              fontSize: "clamp(28px, 4vw, 42px)",
              fontWeight: 800,
              letterSpacing: "-0.025em",
              marginBottom: "16px",
              lineHeight: 1.15,
            }}
          >
            Terms of Service
          </h1>
          <p
            style={{
              maxWidth: "720px",
              margin: "0 auto 24px",
              fontSize: "16.5px",
              color: "var(--muted, #6b7280)",
              lineHeight: 1.6,
            }}
          >
            Welcome to GSearch.AI! These Terms of Service (&quot;Terms&quot;) govern your access to and use of the website, applications, and services provided by Gramosoft Private Limited (&quot;GSearch.AI,&quot; &quot;we,&quot; &quot;us,&quot; or &quot;our&quot;).
          </p>

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              justifyContent: "center",
              gap: "10px",
              fontSize: "13px",
            }}
          >
            <span
              style={{
                background: "#ffffff",
                color: "var(--ink, #14161f)",
                border: "1px solid var(--line, #e5e9ef)",
                padding: "6px 16px",
                borderRadius: "9999px",
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)",
              }}
            >
              <strong>Effective Date:</strong> September 28, 2026
            </span>
            <span
              style={{
                background: "#ffffff",
                color: "var(--ink, #14161f)",
                border: "1px solid var(--line, #e5e9ef)",
                padding: "6px 16px",
                borderRadius: "9999px",
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)",
              }}
            >
              <strong>Last Updated:</strong> September 28, 2026
            </span>
            <span
              style={{
                background: "#ffffff",
                color: "var(--ink, #14161f)",
                border: "1px solid var(--line, #e5e9ef)",
                padding: "6px 16px",
                borderRadius: "9999px",
                fontWeight: 600,
                boxShadow: "0 2px 4px rgba(0,0,0,0.02)",
              }}
            >
              <strong>Operated by:</strong> Gramosoft Private Limited
            </span>
          </div>
        </div>

        {/* Agreement Notice Box */}
        <div
          style={{
            background: "var(--alt, #f5f7fa)",
            border: "1px solid var(--line, #e5e9ef)",
            borderRadius: "16px",
            padding: "20px 24px",
            marginBottom: "32px",
            fontSize: "15px",
            lineHeight: "1.6",
            color: "var(--ink, #14161f)",
          }}
        >
          By creating an account, connecting your third-party integrations, or using our services, you agree to be bound by these Terms. If you do not agree to these Terms, do not use our services.
        </div>

        {/* Google API Services User Data Policy / Limited Use Banner */}
        <div
          style={{
            background: "var(--teal-soft, #e3f7f3)",
            border: "1.5px solid rgba(15, 181, 161, 0.3)",
            borderRadius: "16px",
            padding: "24px 28px",
            marginBottom: "36px",
            boxShadow: "0 6px 20px -8px rgba(15, 181, 161, 0.2)",
          }}
        >
          <h3
            style={{
              color: "var(--teal-deep, #0a8576)",
              fontSize: "18px",
              fontWeight: 700,
              marginTop: 0,
              marginBottom: "12px",
            }}
          >
            Google API Services User Data Policy &amp; Limited Use Disclosure
          </h3>
          <p style={{ fontSize: "15px", lineHeight: "1.6", color: "var(--ink, #14161f)", marginBottom: "12px" }}>
            GSearch.AI&apos;s use and transfer to any other app of information received from Google APIs will adhere to the{" "}
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
          <ul style={{ paddingLeft: "20px", margin: "0 0 16px", color: "var(--ink, #14161f)", fontSize: "14.5px" }}>
            <li style={{ marginBottom: "6px" }}>
              <strong>No Model Training:</strong> We do not use Google Workspace or Google Drive user data to train, retrain, or improve generalized AI/ML models without your explicit consent.
            </li>
            <li>
              <strong>User Revocation:</strong> You may disconnect third-party integrations at any time via your GSearch.AI settings or via your Google Account security permissions.
            </li>
          </ul>
          <div style={{ paddingTop: "12px", borderTop: "1px solid rgba(15, 181, 161, 0.2)" }}>
            <a
              href="https://developers.google.com/terms/api-services-user-data-policy"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "7px 16px",
                borderRadius: "9999px",
                border: "1.5px solid var(--teal, #0fb5a1)",
                color: "var(--teal-deep, #0a8576)",
                background: "#ffffff",
                fontWeight: 700,
                fontSize: "13.5px",
                textDecoration: "none",
              }}
            >
              Read Google API Services User Data Policy &rarr;
            </a>
          </div>
        </div>

        {/* Terms Content Sections */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px", fontSize: "15.5px", lineHeight: "1.7" }}>
          
          {/* Section 1 */}
          <section
            id="section-1"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              1. Description of Service
            </h2>
            <p style={{ margin: 0 }}>
              GSearch.AI provides an AI-powered enterprise search, knowledge intelligence, and document retrieval platform. Our services allow users to index, search, query, and analyze documents and knowledge bases across various data sources, including connected third-party integrations (such as Google Drive, Slack, and cloud storage).
            </p>
          </section>

          {/* Section 2 */}
          <section
            id="section-2"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              2. User Accounts and Security
            </h2>
            <ul style={{ paddingLeft: "20px", margin: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
              <li>You must provide accurate, complete, and current information when creating an account.</li>
              <li>You are responsible for safeguarding your login credentials and for any activities or actions under your account.</li>
              <li>You must immediately notify us of any unauthorized use of your account or security breach.</li>
            </ul>
          </section>

          {/* Section 3 */}
          <section
            id="section-3"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              3. Third-Party Integrations &amp; Google API Services
            </h2>
            <p style={{ marginTop: 0, marginBottom: "16px" }}>
              GSearch.AI allows you to connect third-party accounts, such as Google Drive, to enhance search and knowledge retrieval:
            </p>
            <ul style={{ paddingLeft: "20px", margin: 0, display: "flex", flexDirection: "column", gap: "12px" }}>
              <li>
                <strong>Authorization:</strong> By connecting third-party services, you authorize GSearch.AI to access, retrieve, and index documents and files within the scopes explicitly approved by you during authorization.
              </li>
              <li>
                <strong>Google API Limited Use Disclosure:</strong> GSearch.AI&apos;s use and transfer to any other app of information received from Google APIs will adhere to the{" "}
                <a
                  href="https://developers.google.com/terms/api-services-user-data-policy"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "var(--teal-deep, #0a8576)", fontWeight: 700, textDecoration: "underline" }}
                >
                  Google API Services User Data Policy
                </a>
                , including the Limited Use requirements.
              </li>
              <li>
                <strong>No Model Training on Google User Data:</strong> We do not use Google Workspace or Google Drive user data to train, retrain, or improve generalized AI/ML models without your explicit consent.
              </li>
              <li>
                <strong>Revocation:</strong> You may disconnect third-party integrations at any time via your GSearch.AI settings or via your Google Account security permissions.
              </li>
            </ul>
          </section>

          {/* Section 4 */}
          <section
            id="section-4"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              4. User Content &amp; Intellectual Property
            </h2>
            <ul style={{ paddingLeft: "20px", margin: 0, display: "flex", flexDirection: "column", gap: "12px" }}>
              <li>
                <strong>Your Data:</strong> You retain full ownership and intellectual property rights to any documents, text, queries, and materials you upload or sync to GSearch.AI (&quot;User Content&quot;).
              </li>
              <li>
                <strong>License to Operate:</strong> You grant GSearch.AI a limited, non-exclusive license to process, parse, embed, and index your User Content solely to provide and maintain the services for your account.
              </li>
              <li>
                <strong>Our Intellectual Property:</strong> GSearch.AI, its software, algorithms, branding, logos, and user interface are the exclusive property of Gramosoft Private Limited and protected by copyright and intellectual property laws.
              </li>
            </ul>
          </section>

          {/* Section 5 */}
          <section
            id="section-5"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              5. Acceptable Use
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>You agree not to use GSearch.AI to:</p>
            <ul style={{ paddingLeft: "20px", margin: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
              <li>Violate any applicable local, national, or international law or regulation.</li>
              <li>Process, index, or transmit malware, viruses, or harmful code.</li>
              <li>Reverse-engineer, decompile, or attempt to extract the source code of the platform.</li>
              <li>Interfere with or disrupt the integrity or performance of the service.</li>
              <li>Attempt unauthorized access to other user accounts or systems.</li>
            </ul>
          </section>

          {/* Section 6 */}
          <section
            id="section-6"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              6. Service Availability &amp; Modifications
            </h2>
            <p style={{ margin: 0 }}>
              We strive to maintain high availability; however, services are provided on an &quot;AS IS&quot; and &quot;AS AVAILABLE&quot; basis. We reserve the right to modify, suspend, or discontinue any aspect of the service with reasonable prior notice when possible.
            </p>
          </section>

          {/* Section 7 */}
          <section
            id="section-7"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              7. Limitation of Liability
            </h2>
            <p style={{ marginTop: 0, marginBottom: "12px" }}>
              To the maximum extent permitted by applicable law, Gramosoft Private Limited and its affiliates, officers, employees, or agents shall not be liable for any indirect, incidental, special, consequential, or punitive damages, including loss of profits, data, goodwill, or other intangible losses resulting from:
            </p>
            <ul style={{ paddingLeft: "20px", margin: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
              <li>Your access to or inability to access the service;</li>
              <li>Any third-party conduct or content on the service;</li>
              <li>Unauthorized access, use, or alteration of your content or data.</li>
            </ul>
          </section>

          {/* Section 8 */}
          <section
            id="section-8"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              8. Termination
            </h2>
            <p style={{ margin: 0 }}>
              We may suspend or terminate your access to the service immediately, without prior notice or liability, if you breach these Terms. Upon termination, your right to use the service will immediately cease, and you may request the deletion of your indexed data.
            </p>
          </section>

          {/* Section 9 */}
          <section
            id="section-9"
            style={{
              background: "#ffffff",
              border: "1px solid var(--line, #e5e9ef)",
              borderRadius: "16px",
              padding: "28px",
              boxShadow: "0 2px 6px rgba(0,0,0,0.01)",
            }}
          >
            <h2 style={{ color: "var(--ink, #14161f)", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              9. Changes to These Terms
            </h2>
            <p style={{ margin: 0 }}>
              We may update these Terms periodically. We will notify you of any material changes by updating the &quot;Last Updated&quot; date at the top of this page. Your continued use of the service after such modifications constitutes your acceptance of the updated Terms.
            </p>
          </section>

          {/* Section 10 */}
          <section
            id="section-10"
            style={{
              background: "linear-gradient(135deg, #14161f 0%, #1e212f 100%)",
              border: "1px solid var(--line-2, #d9dfe8)",
              borderRadius: "16px",
              padding: "32px",
              color: "#ffffff",
            }}
          >
            <h2 style={{ color: "#ffffff", fontSize: "20px", fontWeight: 700, marginTop: 0, marginBottom: "14px" }}>
              10. Contact Us
            </h2>
            <p style={{ margin: "0 0 16px", color: "rgba(255,255,255,0.85)", fontSize: "15px" }}>
              If you have any questions or concerns regarding these Terms of Service, please contact us at:
            </p>

            <p style={{ fontWeight: 700, margin: "0 0 4px", fontSize: "16px" }}>Gramosoft Private Limited</p>
            <p style={{ margin: "0 0 20px", color: "rgba(255,255,255,0.8)" }}>GSearch.AI</p>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: "16px",
              }}
            >
              <div
                style={{
                  background: "rgba(255,255,255,0.08)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: "10px",
                  padding: "14px",
                }}
              >
                <span
                  style={{
                    display: "block",
                    textTransform: "uppercase",
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "rgba(255,255,255,0.6)",
                    marginBottom: "4px",
                  }}
                >
                  Company
                </span>
                <span style={{ color: "#ffffff", fontWeight: 600 }}>Gramosoft Private Limited</span>
              </div>

              <div
                style={{
                  background: "rgba(255,255,255,0.08)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: "10px",
                  padding: "14px",
                }}
              >
                <span
                  style={{
                    display: "block",
                    textTransform: "uppercase",
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "rgba(255,255,255,0.6)",
                    marginBottom: "4px",
                  }}
                >
                  Website
                </span>
                <a
                  href="https://gsearchai.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#ffffff", fontWeight: 700, textDecoration: "none" }}
                >
                  https://gsearchai.com &rarr;
                </a>
              </div>

              <div
                style={{
                  background: "rgba(255,255,255,0.08)",
                  border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: "10px",
                  padding: "14px",
                }}
              >
                <span
                  style={{
                    display: "block",
                    textTransform: "uppercase",
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "rgba(255,255,255,0.6)",
                    marginBottom: "4px",
                  }}
                >
                  Email Support
                </span>
                <a
                  href="mailto:support@gsearchai.com"
                  style={{ color: "#ffffff", fontWeight: 700, textDecoration: "none" }}
                >
                  support@gsearchai.com
                </a>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
