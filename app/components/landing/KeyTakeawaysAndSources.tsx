"use client";

import React from "react";
import { CheckOutlined, UnorderedListOutlined } from "@ant-design/icons";

const sourcesData = [
  {
    id: 1,
    author: "McKinsey Global Institute",
    title: "The social economy: Unlocking value and productivity through social technologies",
    domain: "mckinsey.com",
    url: "https://www.mckinsey.com",
  },
  {
    id: 2,
    author: "Gartner",
    title: "Predicts: The Future of Enterprise Search and Knowledge Management",
    domain: "gartner.com",
    url: "https://www.gartner.com",
  },
  {
    id: 3,
    author: "Aslam, S. et al.",
    title: "GEO: Generative Engine Optimization, arXiv:2311.09735",
    domain: "arxiv.org",
    url: "https://arxiv.org",
  },
];

const takeawaysList = [
  "Gsearch connects more than 100 workplace tools and answers questions from all of them in one place.",
  "One person can start free in minutes; the same product scales to an entire company workspace.",
  "Every answer carries a citation, so teams can verify the source before acting on it.",
  "Permissions carry over from your existing tools, so people only see what they are already authorised to see.",
  "Setup takes days, not months: no data migration and no new infrastructure.",
  "Knowledge workers lose an estimated 1.8 hours a day searching for information — time Gsearch is designed to give back.",
];

export default function KeyTakeawaysAndSources() {
  return (
    <section className="block gs-sources-takeaways-section" id="sources">
      <div className="wrap">
        {/* Sources Section */}
        <div className="gs-sources-block">
          <div className="gs-sources-header-row">
            <UnorderedListOutlined className="gs-sources-header-icon" />
            <h3 className="gs-sources-title">Sources</h3>
          </div>

          <ol className="gs-sources-list">
            {sourcesData.map((src) => (
              <li key={src.id} className="gs-source-item">
                <span className="gs-source-badge">[{src.id}]</span>
                <span className="gs-source-text">
                  <strong>{src.author}</strong>, <em>{src.title}</em> —{" "}
                  <a href={src.url} target="_blank" rel="noopener noreferrer">
                    {src.domain}
                  </a>
                </span>
              </li>
            ))}
          </ol>
        </div>

        {/* Key Takeaways Card */}
        <div className="gs-takeaways-card">
          <h3 className="gs-takeaways-title">Key takeaways</h3>
          <ul className="gs-takeaways-list">
            {takeawaysList.map((item, index) => (
              <li key={index}>
                <span className="takeaway-check">
                  <CheckOutlined />
                </span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
