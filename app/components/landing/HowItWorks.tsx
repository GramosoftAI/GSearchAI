import React from "react";
import { Row, Col, Typography } from "antd";

const { Title, Paragraph } = Typography;

const stages = [
  {
    step: "1",
    title: "Crawl",
    body: "Connect your tools and Gsearch brings your docs, tickets, wikis, and files together — no migration, no new system.",
  },
  {
    step: "2",
    title: "Structure",
    body: "Gsearch maps how everything relates — people, projects, products — so it understands your business, not just your words.",
  },
  {
    step: "3",
    title: "Search",
    body: "Ask in plain language and get a cited answer that connects the dots across every source — in chat, in search, or through an agent.",
  },
];

export default function HowItWorks() {
  return (
  <section className="gs-block" id="how">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">Simple by design</div>
        <Title level={2} className="gs-sec-h">Crawl. Structure. Search.</Title>
        <Paragraph className="gs-sec-lede">
          One simple pipeline turns scattered content into answers your team can trust — no data
          project required.
        </Paragraph>
      </div>
      <div className="gs-pipe">
        {stages.map((s, i) => (
          <div className="gs-stage" key={s.step}>
            <span className="step">{s.step}</span>
            <Title level={3} style={{ fontSize: 20, marginBottom: 10 }}>{s.title}</Title>
            <Paragraph style={{ fontSize: 14.5, color: "var(--muted)", margin: 0 }}>{s.body}</Paragraph>
            {i < stages.length - 1 && <span className="arr">→</span>}
          </div>
        ))}
      </div>
    </div>
  </section>
  );
}
