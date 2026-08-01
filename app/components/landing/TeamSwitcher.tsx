"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

const teamsData = [
  {
    id: "support",
    label: "Support",
    title: "Resolve tickets before they escalate",
    description: "Connect a customer issue to past resolutions, product logs, and the right expert — in one answer your reps can trust.",
    pills: ["help desk", "knowledge base", "product logs"],
    example: '"Has this customer hit this issue before?" → answered in seconds, with the past fix attached.',
  },
  {
    id: "sales",
    label: "Sales",
    title: "Walk into every call prepared",
    description: "Connect a contact to their threads, contracts, and open issues across CRM, email, and docs — without the pre-call scramble.",
    pills: ["CRM", "email", "contracts", "tickets"],
    example: "The full relationship in one view — not just the last note.",
  },
  {
    id: "ops",
    label: "Operations",
    title: "Find the record, not the haystack",
    description: "Surface the service record, manual, and approval chain for any asset — connected across every system instead of searched ten times.",
    pills: ["service records", "manuals", "approvals"],
    example: "One asset, one connected view across every tool.",
  },
  {
    id: "eng",
    label: "Engineering",
    title: "Resolve blockers with less disruption",
    description: "Connect code, runbooks, and past incidents to get the decision and the reasoning behind it — without digging through wikis.",
    pills: ["codebase", "runbooks", "incidents", "code reviews"],
    example: '"Why did checkout fail last release?" → answered across services and past incidents.',
  },
  {
    id: "hr",
    label: "HR",
    title: "Answer policy questions in your voice",
    description: "Connect employees to policies, benefits, and people resources instantly — with the source and effective date attached.",
    pills: ["policies", "benefits", "people data"],
    example: "Fewer repeat questions; answers that cite the real document.",
  },
];

export default function TeamSwitcher() {
  const [activeTab, setActiveTab] = useState("support");

  const currentTeam = teamsData.find((t) => t.id === activeTab) || teamsData[0];

  return (
    <section className="block alt gs-teams-section" id="teams" aria-labelledby="teams-h">
      <div className="wrap">
        <div className="sec-center">
          <p className="eyebrow">For every team</p>
          <h2 className="sec-h" id="teams-h">
            Who uses Gsearch?
          </h2>
          <p className="answer">
            Support, sales, operations, engineering, and HR teams all use Gsearch on the same connected knowledge. Each team sees answers drawn from the tools relevant to their work, filtered by the permissions they already hold.
          </p>
        </div>

        {/* Tab switcher buttons */}
        <div className="team-head" role="tablist" aria-label="Teams">
          {teamsData.map((team) => (
            <button
              key={team.id}
              className={`team-btn ${activeTab === team.id ? "active" : ""}`}
              role="tab"
              aria-selected={activeTab === team.id}
              onClick={() => setActiveTab(team.id)}
            >
              {team.label}
            </button>
          ))}
        </div>

        {/* Active Panel with Framer Motion Animation */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentTeam.id}
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -15 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
            className="team-panel active"
          >
            <div className="team-panel-copy">
              <h3>{currentTeam.title}</h3>
              <p>{currentTeam.description}</p>
              <a href="#cta" className="link">
                Book a demo →
              </a>
            </div>

            <div className="team-mock">
              <div className="team-pills">
                {currentTeam.pills.map((pill) => (
                  <span className="pill" key={pill}>
                    {pill}
                  </span>
                ))}
              </div>
              <p className="ex">{currentTeam.example}</p>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
}
