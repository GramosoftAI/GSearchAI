import React from "react";
import { Row, Col, Tag, Typography } from "antd";
import { Tabs } from "antd";
import type { TabsProps } from "antd";
import { teamTabs } from "../lib/content";

const { Title, Paragraph, Link } = Typography;

const items: TabsProps["items"] = teamTabs.map((team) => ({
  key: team.key,
  label: team.label,
  children: (
    <Row gutter={[50, 32]} align="middle" style={{ marginTop: 10 }} className="gs-team-panel">
      <Col xs={24} md={12}>
        <Title level={3} style={{ fontSize: 25, marginBottom: 12 }}>{team.heading}</Title>
        <Paragraph style={{ fontSize: 16.5, color: "var(--muted)" }}>{team.body}</Paragraph>
        <Link href="#cta" style={{ color: "var(--teal-deep)", fontWeight: 700, marginTop: 14, display: "inline-flex" }}>
          {team.ctaLabel}
        </Link>
      </Col>
      <Col xs={24} md={12}>
        <div className="gs-team-mock">
          {team.pills.map((pill) => (
            <Tag
              key={pill}
              style={{ fontSize: 12.5, fontWeight: 600, color: "var(--teal-deep)", background: "var(--teal-soft)", border: "none", borderRadius: 9, padding: "6px 12px", margin: "0 8px 10px 0" }}
            >
              {pill}
            </Tag>
          ))}
          <Paragraph style={{ fontSize: 14, color: "var(--muted)", marginTop: 8 }}>
            {team.example}
          </Paragraph>
        </div>
      </Col>
    </Row>
  ),
}));

export default function TeamSwitcher() {
  return (
  <section className="gs-block" id="teams">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">For every team</div>
        <Title level={2} className="gs-sec-h">Real value for every team, every day.</Title>
      </div>
      <Tabs defaultActiveKey="support" centered items={items} size="large" />
    </div>
  </section>
  );
}
