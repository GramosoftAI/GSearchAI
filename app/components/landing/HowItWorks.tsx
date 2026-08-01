"use client";
import React from "react";

export default function HowItWorks() {
  return (
    <section className="block alt gs-how-section" id="how" aria-labelledby="how-h">
      <div className="wrap">
        <div className="sec-center">
          <p className="eyebrow">Simple by design</p>
          <h2 className="sec-h" id="how-h">How does Gsearch work?</h2>
          <p className="answer">Gsearch works in three steps: it crawls the tools you already use, structures what it finds into a connected map of your business, and then answers questions against that map. Setup takes days because nothing has to be migrated or rebuilt.</p>
        </div>

        <ol className="steps">
          <li className="step-card step-card-1">
            <div className="step-num">1</div>
            <b>Crawl — bring everything together</b>
            <span>Connect your tools and Gsearch gathers your docs, tickets, wikis, and files. No migration, no new system to maintain.</span>
          </li>
          <li className="step-card step-card-2">
            <div className="step-num">2</div>
            <b>Structure — map how it all relates</b>
            <span>Gsearch maps the relationships between people, projects, and products — the way a brain connects memories, not the way a filing cabinet stores paper.</span>
          </li>
          <li className="step-card step-card-3">
            <div className="step-num">3</div>
            <b>Search — ask and act</b>
            <span>Ask in plain language and get a cited answer that draws on every connected source, in search, in chat, or through an agent.</span>
          </li>
        </ol>

        {/* DIAGRAM 2: 3-Stage Pipeline Illustration */}
        <figure className="illus illus-pipeline" aria-labelledby="illus2-cap">
          <svg viewBox="0 0 820 190" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Three stage pipeline: crawl gathers sources, structure maps relationships, search returns a cited answer">
            <defs>
              <linearGradient id="pipeGrad1" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#0FB5A1"/>
                <stop offset="100%" stopColor="#7C6CF0"/>
              </linearGradient>
              <linearGradient id="pipeGrad2" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#7C6CF0"/>
                <stop offset="100%" stopColor="#F4C24B"/>
              </linearGradient>
            </defs>

            <g fontFamily="Plus Jakarta Sans,sans-serif" textAnchor="middle">
              {/* Stage 1: Crawl Card */}
              <g className="pipe-stage pipe-stage-1">
                <rect x="24" y="46" width="200" height="100" rx="16" fill="#ffffff" stroke="#CBD5E1" strokeWidth="1.5" className="pipe-card"/>
                {/* Floating data bubbles */}
                <circle cx="80" cy="86" r="9" fill="#0FB5A1" className="pipe-bubble bubble-1"/>
                <circle cx="108" cy="72" r="9" fill="#7C6CF0" className="pipe-bubble bubble-2"/>
                <circle cx="136" cy="92" r="9" fill="#0FB5A1" className="pipe-bubble bubble-3"/>
                <circle cx="168" cy="76" r="9" fill="#F4C24B" className="pipe-bubble bubble-4"/>
                <circle cx="96" cy="108" r="9" fill="#0FB5A1" className="pipe-bubble bubble-5"/>
                <text x="124" y="136" fontSize="13" fontWeight="800" fill="#0F172A">1 · Crawl</text>
              </g>

              {/* Arrow 1 */}
              <g className="pipe-arrow pipe-arrow-1">
                <path d="M238 96 L266 96" stroke="url(#pipeGrad1)" strokeWidth="3" strokeLinecap="round" className="pipe-line"/>
                <polygon points="266,90 278,96 266,102" fill="#7C6CF0" className="pipe-head"/>
              </g>

              {/* Stage 2: Structure Card */}
              <g className="pipe-stage pipe-stage-2">
                <rect x="294" y="46" width="200" height="100" rx="16" fill="#ffffff" stroke="#CBD5E1" strokeWidth="1.5" className="pipe-card"/>
                {/* Graph constellation */}
                <g stroke="#0FB5A1" strokeWidth="1.6" fill="none" className="pipe-graph-lines">
                  <path d="M340 78 L394 66 L436 92 L370 108 Z"/>
                  <path d="M394 66 L370 108"/>
                  <path d="M340 78 L436 92"/>
                </g>
                <circle cx="340" cy="78" r="5.5" fill="#0FB5A1" className="pipe-node node-1"/>
                <circle cx="394" cy="66" r="5.5" fill="#7C6CF0" className="pipe-node node-2"/>
                <circle cx="436" cy="92" r="5.5" fill="#F4C24B" className="pipe-node node-3"/>
                <circle cx="370" cy="108" r="5.5" fill="#0FB5A1" className="pipe-node node-4"/>
                <text x="394" y="136" fontSize="13" fontWeight="800" fill="#0F172A">2 · Structure</text>
              </g>

              {/* Arrow 2 */}
              <g className="pipe-arrow pipe-arrow-2">
                <path d="M508 96 L536 96" stroke="url(#pipeGrad2)" strokeWidth="3" strokeLinecap="round" className="pipe-line"/>
                <polygon points="536,90 548,96 536,102" fill="#F4C24B" className="pipe-head"/>
              </g>

              {/* Stage 3: Search Card */}
              <g className="pipe-stage pipe-stage-3">
                <rect x="564" y="46" width="232" height="100" rx="16" fill="#ffffff" stroke="#CBD5E1" strokeWidth="1.5" className="pipe-card"/>
                <rect x="590" y="68" width="180" height="11" rx="5.5" fill="#E2E8F0" className="pipe-search-line line-1"/>
                <rect x="590" y="86" width="140" height="11" rx="5.5" fill="#E2E8F0" className="pipe-search-line line-2"/>
                <rect x="590" y="106" width="52" height="16" rx="6" fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="1" className="pipe-cit cit-1"/>
                <rect x="650" y="106" width="52" height="16" rx="6" fill="#F5F3FF" stroke="#7C6CF0" strokeWidth="1" className="pipe-cit cit-2"/>
                <text x="680" y="136" fontSize="13" fontWeight="800" fill="#0F172A">3 · Search</text>
              </g>
            </g>
          </svg>
          <figcaption id="illus2-cap">One pipeline: gather what exists, map how it relates, answer with the source attached.</figcaption>
        </figure>
      </div>
    </section>
  );
}
