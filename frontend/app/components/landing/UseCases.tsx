"use client";

import { Row, Col, Card, Typography } from "antd";

const { Title, Paragraph } = Typography;

const useCases = [
  { icon: "🛟", title: "Product support", body: "Help with features, setup, and issues — answered instantly from your docs." },
  { icon: "✍️", title: "Content writer", body: "Draft on-brand copy and replies using your existing knowledge." },
  { icon: "🤝", title: "Sales assistant", body: "Research a deal, prep for a call, and keep the CRM up to date." },
  { icon: "📊", title: "Data analyst", body: "Generate insights from your product and business data on demand." },
  { icon: "📘", title: "Employee handbook", body: "Answers to company policies, in your company's voice." },
  { icon: "🚀", title: "Onboarding guide", body: "Step-by-step guidance that walks new hires from question to answer." },
];

export default function UseCases() {
  return (
    <section className="gs-block alt">
      <div className="wrap">
        <div className="gs-sec-center">
          <div className="gs-eyebrow">Agents &amp; workflows</div>
          <Title level={2} className="gs-sec-h" style={{ color: "var(--ink)", fontWeight: 800 }}>Put AI to work on your hardest problems.</Title>
          <Paragraph className="gs-sec-lede" style={{ fontSize: "18px", paddingBottom: 10, color: "var(--muted)" }}>
            Build AI assistants with the right knowledge, context, and tools for any job — a team
            of specialists your whole company can use.
          </Paragraph>
        </div>
        <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
          {useCases.map((uc) => (
            <Col xs={24} sm={12} lg={8} key={uc.title}>
              <Card
                className="gs-ucard"
                style={{ height: "100%", border: "1px solid var(--line)", borderRadius: 16 }}
                styles={{ body: { padding: 24 } }}
              >
                <div style={{ display: "inline-grid", placeItems: "center", width: 42, height: 42, borderRadius: 11, fontSize: 20, marginBottom: 14, background: "var(--teal-soft)", color: "var(--teal-deep)" }}>
                  {uc.icon}
                </div>
                <Title level={3} style={{ fontSize: 18, marginBottom: 7, color: "var(--ink)" }}>{uc.title}</Title>
                <Paragraph style={{ fontSize: 14.5, color: "var(--muted)", margin: 0 }}>{uc.body}</Paragraph>
              </Card>
            </Col>
          ))}
        </Row>
      </div>
    </section>
  );
}
