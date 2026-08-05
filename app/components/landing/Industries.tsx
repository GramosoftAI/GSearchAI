"use client";

import React from "react";
import { ShieldCheck, ShieldBan, Cloud } from "lucide-react";

const securityCards = [
  {
    icon: ShieldCheck,
    title: "Enterprise security controls",
    body: "Independent third-party auditing of our security and operational controls, reviewed on a recurring schedule.",
  },
  {
    icon: ShieldBan,
    title: "Zero data retention",
    body: "Your queries and data are never stored for model training, and never leave your chosen environment.",
  },
  {
    icon: Cloud,
    title: "Bring your own cloud and keys",
    body: "Full data sovereignty: deploy inside your own environment with the model provider and keys you choose.",
  },
];

const securityRows = [
  {
    title: "Permission-aware",
    body: "Users only ever see what they are already authorised to access.",
  },
  {
    title: "Content governance",
    body: "Verify trusted sources and suppress outdated content.",
  },
  {
    title: "Sensitive data detection",
    body: "Automatically flag and restrict personal data for admin review.",
  },
  {
    title: "Full audit trails",
    body: "Every interaction logged for complete visibility.",
  },
];

export default function Industries() {
  return (
    <section className="block gs-security-section" id="security" aria-labelledby="sec-h">
      <div className="wrap">
        <div className="sec-center">
          <p className="eyebrow">Security, compliance, governance</p>
          <h2 className="sec-h" id="sec-h">
            Is company data safe with Gsearch?
          </h2>
          <p className="answer">
            Yes. Gsearch enforces the permissions already set in your connected tools, so nobody sees content they are not cleared for. Your queries and data are never used to train models, and you can run the platform inside your own cloud environment.
          </p>
        </div>

        {/* 3 Top Security Cards */}
        <div className="sec-grid">
          {securityCards.map((card) => {
            const Icon = card.icon;
            return (
              <div className="scard" key={card.title}>
                <div className="si" aria-hidden="true">
                  <Icon size={22} strokeWidth={2.2} />
                </div>
                <h3>{card.title}</h3>
                <p>{card.body}</p>
              </div>
            );
          })}
        </div>

        {/* Split Section with Shield Illustration */}
        <div className="split sec-split">
          <div className="split-copy">
            <h3>Answers stay inside your boundary</h3>
            <p>
              Gsearch enforces the access rules your tools already have. Nothing is copied out, nothing trains a model, and every answer can be traced back to the document it came from.
            </p>
            <p className="band" aria-hidden="true"></p>
          </div>

          <figure className="illus sec-illus" aria-labelledby="illus3-cap">
            <svg
              viewBox="0 0 400 260"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              aria-label="Shield protecting layered company data with permission checks and an audit trail"
            >
              <defs>
                <filter id="glowShield" x="-10%" y="-10%" width="120%" height="120%">
                  <feDropShadow dx="0" dy="8" stdDeviation="12" floodColor="#0FB5A1" floodOpacity="0.15" />
                </filter>
              </defs>

              {/* Shield outline */}
              <path
                d="M200 26l104 38v74c0 56-44 84-104 96-60-12-104-40-104-96V64z"
                fill="#F4FCFA"
                stroke="#0FB5A1"
                strokeWidth="2.4"
                className="sec-shield-path"
                filter="url(#glowShield)"
              />

              {/* Center Lock Icon */}
              <g transform="translate(168,86)" className="sec-lock-group">
                <path
                  d="M10 26v-9a22 22 0 0144 0v9"
                  fill="none"
                  stroke="#0FB5A1"
                  strokeWidth="3.4"
                  className="sec-lock-arch"
                />
                <rect x="4" y="26" width="56" height="42" rx="10" fill="#0FB5A1" className="sec-lock-body" />
                <circle cx="32" cy="45" r="6" fill="#fff" />
                <rect x="29" y="45" width="6" height="13" rx="3" fill="#fff" />
              </g>

              {/* Permission & Audit badges */}
              <g fontFamily="Plus Jakarta Sans,sans-serif" fontSize="11" fontWeight="700" textAnchor="middle" className="sec-badges-group">
                <rect x="120" y="176" width="76" height="24" rx="8" fill="#fff" stroke="#BFE9E1" className="sec-badge-box badge-1" />
                <text x="158" y="192" fill="#0A8576">
                  Permissions
                </text>
                <rect x="204" y="176" width="76" height="24" rx="8" fill="#fff" stroke="#BFE9E1" className="sec-badge-box badge-2" />
                <text x="242" y="192" fill="#0A8576">
                  Audit log
                </text>
              </g>

              {/* Pulsing floating sparkles/dots */}
              <g fill="#F4C24B" opacity=".85" className="sec-dots-group">
                <circle cx="112" cy="70" r="5" className="sec-dot dot-1" />
                <circle cx="292" cy="82" r="5" className="sec-dot dot-2" />
                <circle cx="300" cy="150" r="4" className="sec-dot dot-3" />
                <circle cx="104" cy="142" r="4" className="sec-dot dot-4" />
              </g>
            </svg>
            <figcaption id="illus3-cap">
              Permission-aware by design, with a full audit trail on every answer.
            </figcaption>
          </figure>
        </div>

        {/* 4 Bottom Feature Rows */}
        <div className="sec-row2">
          {securityRows.map((row) => (
            <div className="srow" key={row.title}>
              <h4>{row.title}</h4>
              <p>{row.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
