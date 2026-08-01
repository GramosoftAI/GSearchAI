"use client";
import React from "react";
import Link from "next/link";

export default function SoloVsWorkspace() {
  return (
    <section className="block gs-paths-section" id="paths" aria-labelledby="paths-h">
      <div className="wrap">
        <div className="sec-center">
          <p className="eyebrow">Solo or company-wide</p>
          <h2 className="sec-h" id="paths-h">
            Can one person use Gsearch, or is it only for companies?
          </h2>
          <p className="answer">
            Both. Gsearch works for a single person connecting their own accounts, and for a whole company rolling it out across departments. It is the same product either way — the difference is whose data is connected and who can see it.
          </p>
        </div>
        <div className="paths">
          {/* Article 1: Solo */}
          <article className="path path-solo">
            <svg
              className="picon picon-solo"
              viewBox="0 0 260 96"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              aria-label="One person connected to their own private accounts"
            >
              <circle cx="60" cy="48" r="20" fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="2" className="solo-user-bg" />
              <circle cx="60" cy="42" r="7" fill="#0FB5A1" className="solo-user-head" />
              <path d="M48 60c3-7 21-7 24 0" fill="#0FB5A1" className="solo-user-body" />
              
              <g stroke="#CBD5E1" strokeWidth="1.6" className="solo-lines">
                <path d="M84 48h28" className="line-1" />
                <path d="M84 48l30-22" className="line-2" />
                <path d="M84 48l30 22" className="line-3" />
              </g>

              <rect x="118" y="16" width="58" height="22" rx="7" fill="#fff" stroke="#E2E8F0" className="solo-card card-1" />
              <rect x="118" y="38" width="58" height="22" rx="7" fill="#fff" stroke="#E2E8F0" className="solo-card card-2" />
              <rect x="118" y="60" width="58" height="22" rx="7" fill="#fff" stroke="#E2E8F0" className="solo-card card-3" />

              <g fill="#0FB5A1" opacity=".65" className="solo-dots">
                <circle cx="132" cy="27" r="4" />
                <circle cx="132" cy="49" r="4" />
                <circle cx="132" cy="71" r="4" />
              </g>

              <rect x="192" y="34" width="46" height="30" rx="8" fill="#F4C24B" opacity=".2" className="solo-plus-bg" />
              <path
                d="M208 48h14M215 41v14"
                stroke="#E0A92E"
                strokeWidth="2.4"
                strokeLinecap="round"
                className="solo-plus-icon"
              />
            </svg>
            <p className="ptag ptag-solo">For yourself</p>
            <h3>Connect your own tools</h3>
            <p>
              Sign up, connect the accounts you personally use, and start asking questions in minutes. Nothing is shared with anyone else, and no admin approval is needed.
            </p>
            <ul>
              <li>Free to start, no credit card and no IT ticket</li>
              <li>Your personal connectors stay private to you</li>
              <li>Search your own mail, files, notes, and tasks in one place</li>
              <li>Data is fetched in real time, never duplicated or stored</li>
            </ul>
            <Link href="/register" className="btn btn-out">
              Start for free
            </Link>
          </article>

          {/* Article 2: Workspace / Company */}
          <article className="path path-team">
            <svg
              className="picon picon-team"
              viewBox="0 0 260 96"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              aria-label="Multiple teams sharing connected company sources with permissions"
            >
              <g fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="2" className="team-users-bg">
                <circle cx="42" cy="30" r="14" className="u-1" />
                <circle cx="42" cy="66" r="14" className="u-2" />
                <circle cx="78" cy="48" r="14" className="u-3" />
              </g>
              <g fill="#0FB5A1" className="team-users-fg">
                <circle cx="42" cy="26" r="5" />
                <circle cx="42" cy="62" r="5" />
                <circle cx="78" cy="44" r="5" />
                <path d="M34 38c2-5 14-5 16 0" />
                <path d="M34 74c2-5 14-5 16 0" />
                <path d="M70 56c2-5 14-5 16 0" />
              </g>
              <g stroke="#CBD5E1" strokeWidth="1.6" className="team-lines">
                <path d="M96 48h26" />
                <path d="M56 30l24 12" />
                <path d="M56 66l24-12" />
              </g>
              <rect x="126" y="20" width="86" height="56" rx="12" fill="#fff" stroke="#BFE9E1" className="team-workspace-card" />
              <rect x="140" y="34" width="58" height="8" rx="4" fill="#EEF2F6" className="team-line line-1" />
              <rect x="140" y="48" width="44" height="8" rx="4" fill="#EEF2F6" className="team-line line-2" />
              <rect x="140" y="60" width="30" height="8" rx="4" fill="#E3F7F3" className="team-line line-3" />
              
              <g transform="translate(216,36)" className="team-lock">
                <rect width="26" height="24" rx="6" fill="#F4C24B" opacity=".22" />
                <path d="M8 12v-3a5 5 0 0110 0v3" fill="none" stroke="#E0A92E" strokeWidth="2" />
                <rect x="6" y="12" width="14" height="10" rx="3" fill="#E0A92E" />
              </g>
            </svg>
            <p className="ptag ptag-team">For your company</p>
            <h3>Connect your whole workspace</h3>
            <p>
              Roll Gsearch out across departments with shared connectors, user groups, and the permissions your tools already enforce. Everyone gets answers scoped to their role.
            </p>
            <ul>
              <li>Shared connectors configured once for all users</li>
              <li>Existing permissions carry over automatically</li>
              <li>User groups control which teams reach which sources</li>
              <li>Admin controls, audit logs, and your own cloud deployment</li>
            </ul>
            <a href="#cta" className="btn btn-teal">
              Book a demo
            </a>
          </article>
        </div>
      </div>
    </section>
  );
}
