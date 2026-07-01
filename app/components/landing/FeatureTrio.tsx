import React from "react";
import { Row, Col, Card, Typography } from "antd";
import { Eye, MessageSquare, Lock } from "lucide-react";

const { Title, Paragraph } = Typography;

const features = [
  {
    icon: Eye,
    title: "Get the full picture, fast",
    body: "Gsearch pulls from every tool your team uses, connects the dots across them, and gives you answers grounded in your actual data.",
  },
  {
    icon: MessageSquare,
    title: "Think it through with AI that knows your work",
    body: "Ask a question, explore an idea, or work through a problem. Gsearch understands your context, not just your keywords.",
  },
  {
    icon: Lock,
    title: "Your data never leaves",
    body: "Pull answers in real time straight from the source. Sensitive data stays where it is, with no copies and no waiting.",
  },
];

export default function FeatureTrio() {
  return (
  <section className="gs-block" id="product">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">One place for everything</div>
        <Title level={2} className="gs-sec-h">Gsearch meets your knowledge where it already lives.</Title>
        <Paragraph className="gs-sec-lede">
          No migration, no new system to learn. Connect your tools and your team starts getting
          answers in minutes — with permissions that carry over automatically.
        </Paragraph>
      </div>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {features.map((f) => {
          const Icon = f.icon;
          return (
            <Col xs={24} md={8} key={f.title}>
              <Card
                className="gs-fcard"
                style={{ height: "100%", border: "1px solid var(--line)", borderRadius: 16 }}
                styles={{ body: { padding: 30 } }}
              >
                <div className="ic" style={{ width: 48, height: 48, borderRadius: 13, display: "grid", placeItems: "center", marginBottom: 18, background: "var(--teal-soft)", color: "var(--teal-deep)" }}>
                  <Icon size={22} strokeWidth={2} />
                </div>
                <Title level={3} style={{ fontSize: 19, marginBottom: 10 }}>{f.title}</Title>
                <Paragraph style={{ fontSize: 15, color: "var(--muted)", margin: 0 }}>{f.body}</Paragraph>
              </Card>
            </Col>
          );
        })}
      </Row>
    </div>
  </section>
  );
}
