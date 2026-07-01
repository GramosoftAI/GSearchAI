import React from "react";
import { Card, Row, Col, Typography } from "antd";
import { Tabs } from "antd";
import type { TabsProps } from "antd";
import { capabilityTabs } from "../lib/content";

const { Title, Paragraph, Link } = Typography;

const items: TabsProps["items"] = capabilityTabs.map((tab) => ({
  key: tab.key,
  label: tab.label,
  children: (
    <Row gutter={[50, 32]} align="middle" style={{ marginTop: 10 }}>
      <Col xs={24} md={12}>
        <Title level={3} style={{ fontSize: 26, marginBottom: 14 }}>{tab.heading}</Title>
        <Paragraph style={{ fontSize: 16.5, color: "var(--muted)", marginBottom: 18 }}>{tab.body}</Paragraph>
        <Link href="#how" style={{ color: "var(--teal-deep)", fontWeight: 700, fontSize: 14.5 }}>
          See how it works →
        </Link>
      </Col>
      <Col xs={24} md={12}>
        <div className="gs-tp-mock">
          {tab.mockRows.map((row, i) => (
            <div className="gs-mockrow" key={i}>
              <span className="dot" style={{ background: row.color }} />
              <span dangerouslySetInnerHTML={{ __html: row.text }} />
            </div>
          ))}
        </div>
      </Col>
    </Row>
  ),
}));

export default function CapabilityTabs() {
  return (
  <section className="gs-block">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">One platform, every job</div>
        <Title level={2} className="gs-sec-h">From a question to a finished task.</Title>
      </div>
      <Tabs
        defaultActiveKey="answers"
        centered
        items={items}
        className="gs-capability-tabs"
        size="large"
      />
    </div>
  </section>
  );
}
