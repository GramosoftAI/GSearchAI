import React from "react";
import { Row, Col, Card, Typography } from "antd";
import { Plane, Car, Shield, Factory } from "lucide-react";

const { Title, Paragraph } = Typography;

const industries = [
  {
    icon: Plane,
    title: "Aviation & MRO",
    body: "Connect manuals, airworthiness directives, and service records to the right part — in seconds, not hours.",
  },
  {
    icon: Car,
    title: "Automotive",
    body: "Link service histories, warranties, and dealer processes into one answer your team can act on.",
  },
  {
    icon: Shield,
    title: "Insurance",
    body: "Trace a policy, claim, or rule to every document and dependency it touches — fully cited.",
  },
  {
    icon: Factory,
    title: "Manufacturing",
    body: "Find the spec, SOP, and approval chain for any asset across every system at once.",
  },
];

export default function Industries() {
  return (
  <section className="gs-block">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">Built for your world</div>
        <Title level={2} className="gs-sec-h">Knowledge that&apos;s tuned to your industry.</Title>
        <Paragraph className="gs-sec-lede">
          Gsearch understands the documents, parts, and processes specific to how your business
          actually runs.
        </Paragraph>
      </div>
      <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
        {industries.map((ind) => {
          const Icon = ind.icon;
          return (
            <Col xs={24} sm={12} lg={6} key={ind.title}>
              <Card
                className="gs-icard"
                style={{ height: "100%", border: "1px solid var(--line)", borderRadius: 16 }}
                styles={{ body: { padding: 26 } }}
              >
                <div style={{ color: "var(--teal-deep)", marginBottom: 14 }}>
                  <Icon size={28} strokeWidth={1.8} />
                </div>
                <Title level={3} style={{ fontSize: 17, marginBottom: 8 }}>{ind.title}</Title>
                <Paragraph style={{ fontSize: 14, color: "var(--muted)", margin: 0 }}>{ind.body}</Paragraph>
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  </section>
  );
}
