"use client";

import React from "react";
import { Typography, Tag } from "antd";
import { CheckOutlined, CloseOutlined, InfoCircleOutlined } from "@ant-design/icons";

const { Title, Paragraph } = Typography;

const comparisonData = [
  {
    key: "1",
    criteria: "What you get back",
    keyword: "A list of links",
    standardAi: "A written answer",
    gsearch: "A cited answer from your data",
    // gsearchBadge: "Cited & Real-Time",
  },
  {
    key: "2",
    criteria: "Knows your company",
    keyword: "No",
    standardAi: "No",
    gsearch: "Yes — connected to your tools",
    // gsearchBadge: "100+ Connectors",
  },
  {
    key: "3",
    criteria: "Source you can verify",
    keyword: "You check manually",
    standardAi: "Often none",
    gsearch: "Citation on every answer",
    // gsearchBadge: "Direct Citations",
  },
  {
    key: "4",
    criteria: "Respects access rules",
    keyword: "Per tool only",
    standardAi: "Not applicable",
    gsearch: "Permissions carry over",
    // gsearchBadge: "Enterprise Security",
  },
  {
    key: "5",
    criteria: "Takes action for you",
    keyword: "No",
    standardAi: "Limited",
    gsearch: "Agents and workflows",
    // gsearchBadge: "AI Agents",
  },
];

export default function SearchComparison() {
  return (
    <section className="gs-block block alt cmp-section" id="compare" aria-labelledby="cmp-h">
      <div className="wrap">
        <div className="gs-sec-center">
          <div className="gs-eyebrow">How it compares</div>
          <Title level={2} className="gs-sec-h" id="cmp-h" style={{ color: "var(--ink, #0f172a)", fontWeight: 800 }}>
            How is Gsearch different from regular search?
          </Title>
          <Paragraph className="gs-sec-lede" style={{ fontSize: "16.5px", color: "var(--muted, #64748b)" }}>
            Regular search returns the document closest to your words. Gsearch connects information across tools to answer questions no single document holds, and cites each source. The table below sets out the practical differences.
          </Paragraph>
        </div>

        {/* Responsive Table Wrapper */}
        <div className="cmp-table-wrapper">
          <table className="cmp-table">
            <caption className="sr-only">
              Comparison of keyword search, standard AI chat, and Gsearch across five buying criteria.
            </caption>
            <thead>
              <tr>
                <th scope="col" className="cmp-col-criteria">Criteria</th>
                <th scope="col" className="cmp-col-other">Keyword search</th>
                <th scope="col" className="cmp-col-other">Standard AI chat</th>
                <th scope="col" className="cmp-col-gsearch">
                  <div className="gsearch-header-badge">
                    <span>Gsearch</span>
                    <Tag color="#0FB5A1" style={{ borderRadius: 99, fontWeight: 700, margin: 0 }}>Recommended</Tag>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {comparisonData.map((row) => (
                <tr key={row.key} className="cmp-row">
                  <td className="cmp-cell-criteria">
                    <strong>{row.criteria}</strong>
                  </td>
                  <td className="cmp-cell-neutral">
                    <span className="cmp-text-muted">
                      {row.keyword === "No" ? (
                        <Tag icon={<CloseOutlined />} color="default" style={{ borderRadius: 6 }}>No</Tag>
                      ) : (
                        row.keyword
                      )}
                    </span>
                  </td>
                  <td className="cmp-cell-neutral">
                    <span className="cmp-text-muted">
                      {row.standardAi === "No" ? (
                        <Tag icon={<CloseOutlined />} color="default" style={{ borderRadius: 6 }}>No</Tag>
                      ) : (
                        row.standardAi
                      )}
                    </span>
                  </td>
                  <td className="cmp-cell-gsearch">
                    <div className="gsearch-cell-content">
                      <span className="gsearch-check-icon">
                        <CheckOutlined />
                      </span>
                      <span className="gsearch-text">{row.gsearch}</span>
                      {/* {row.gsearchBadge && (
                        <Tag color="cyan" style={{ borderRadius: 6, fontWeight: 600, fontSize: 11, marginLeft: "auto" }}>
                          {row.gsearchBadge}
                        </Tag>
                      )} */}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
