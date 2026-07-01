import React from "react";
import { Row, Col, Card, Typography } from "antd";
import { Shield, Ban, Cloud } from "lucide-react";

const { Title, Paragraph } = Typography;

const securityCards = [
  { icon: Shield, title: "Enterprise security", body: "Rigorous third-party auditing of our security and operational controls." },
  { icon: Ban, title: "Zero data retention", body: "Your queries and data are never stored or used to train models." },
  { icon: Cloud, title: "Bring your own cloud & keys", body: "Full data sovereignty with deployment in your own environment and choice of models." },
];

const securityRows = [
  { title: "Permission-aware", body: "Users only ever see what they're authorized to access." },
  { title: "Content governance", body: "Verify trusted sources and suppress outdated content." },
  { title: "Sensitive data detection", body: "Automatically flag and restrict PII for admin review." },
  { title: "Full audit trails", body: "Every interaction logged for complete visibility." },
];

export default function Security() {
  return (
  <section className="gs-block" id="security">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">Security, compliance, governance</div>
        <Title level={2} className="gs-sec-h">Built for teams where trust isn&apos;t optional.</Title>
        <Paragraph className="gs-sec-lede">
          Gsearch protects your company&apos;s knowledge by enforcing your policies, securing
          your data, and keeping every answer accountable.
        </Paragraph>
      </div>

      <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
        {securityCards.map((c) => {
          const Icon = c.icon;
          return (
            <Col xs={24} md={8} key={c.title}>
              <Card
                className="gs-scard"
                style={{ height: "100%", border: "1px solid var(--line)", borderRadius: 16 }}
                styles={{ body: { padding: 28 } }}
              >
                <div style={{ width: 46, height: 46, borderRadius: 12, display: "grid", placeItems: "center", marginBottom: 16, background: "var(--teal-soft)", color: "var(--teal-deep)" }}>
                  <Icon size={22} strokeWidth={2} />
                </div>
                <Title level={3} style={{ fontSize: 18, marginBottom: 9 }}>{c.title}</Title>
                <Paragraph style={{ fontSize: 14.5, color: "var(--muted)", margin: 0 }}>{c.body}</Paragraph>
              </Card>
            </Col>
          );
        })}
      </Row>

      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        {securityRows.map((r) => (
          <Col xs={24} sm={12} lg={6} key={r.title}>
            <Card
              className="gs-srow"
              style={{ height: "100%", background: "var(--alt)", border: "1px solid var(--line)", borderRadius: 12 }}
              styles={{ body: { padding: 20 } }}
            >
              <Title level={4} style={{ fontSize: 14.5, marginBottom: 6 }}>{r.title}</Title>
              <Paragraph style={{ fontSize: 13, color: "var(--muted)", margin: 0 }}>{r.body}</Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  </section>
  );
}
