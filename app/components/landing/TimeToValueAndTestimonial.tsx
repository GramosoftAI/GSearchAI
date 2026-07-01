import React from "react";
import { Row, Col, Card, Typography, Statistic } from "antd";

const { Title, Paragraph, Text } = Typography;

const ttvItems = [
  { n: "3 days", title: "Average first connector live", body: "Most teams connect their first tools and see answers within the first week." },
  { n: "0", title: "Migration projects required", body: "Gsearch reads from your tools in place — nothing to move, nothing to copy." },
  { n: "100%", title: "Permissions carried over", body: "Existing access rules apply automatically, from day one." },
];

const stats = [
  { big: "47%", lbl: "increase in team productivity" },
  { big: "49%", lbl: "reduction in ticket backlog" },
  { big: "80%", lbl: "daily adoption in first 3 months" },
  { big: "500+", lbl: "enterprises building on Gsearch" },
];

export default function TimeToValueAndTestimonial() {
  return (
  <>
    <section className="gs-block">
      <div className="wrap">
        <div className="gs-sec-center">
          <div className="gs-eyebrow">Fast time to value</div>
          <Title level={2} className="gs-sec-h">Up and running in days, not months.</Title>
          <Paragraph className="gs-sec-lede">
            Gsearch works with the tools and permissions you already have. No new
            infrastructure, no long rollout, no engineering backlog.
          </Paragraph>
        </div>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          {ttvItems.map((item) => (
            <Col xs={24} md={8} key={item.title}>
              <div className="gs-ttv-item">
                <div style={{ fontSize: 38, fontWeight: 800, color: "var(--teal-deep)", letterSpacing: "-0.02em" }}>
                  {item.n}
                </div>
                <Title level={3} style={{ fontSize: 17, margin: "10px 0 8px" }}>{item.title}</Title>
                <Paragraph style={{ fontSize: 14.5, color: "var(--muted)", margin: 0 }}>{item.body}</Paragraph>
              </div>
            </Col>
          ))}
        </Row>

        <div className="gs-testi" style={{ marginTop: 40 }}>
          <div>
            <Paragraph style={{ fontSize: 24, fontWeight: 700, color: "var(--ink)", lineHeight: 1.32, letterSpacing: "-0.02em" }}>
              Gsearch gave our support team a{" "}
              <Text style={{ color: "var(--teal-deep)", fontWeight: 700 }}>single source of truth</Text>{" "}
              across every tool we use — tickets resolve faster and reps trust the answer.
            </Paragraph>
            <div className="who" style={{ marginTop: 22, display: "flex", alignItems: "center", gap: 12 }}>
              <span className="av" style={{ width: 46, height: 46, borderRadius: "50%", background: "linear-gradient(135deg,var(--teal),var(--gold))", display: "block" }} />
              <span className="nm">
                <Text strong style={{ display: "block", color: "var(--ink)", fontWeight: 700, fontSize: 15 }}>VP of Customer Support</Text>
                <Text style={{ fontSize: 13.5, color: "var(--muted)" }}>Enterprise client</Text>
              </span>
            </div>
          </div>
          <div className="gs-stat-grid">
            {stats.map((s) => (
              <Card
                key={s.lbl}
                className="gs-stat"
                style={{ background: "var(--alt)", border: "1px solid var(--line)", borderRadius: 14 }}
                styles={{ body: { padding: 22 } }}
              >
                <div style={{ fontSize: 34, fontWeight: 800, color: "var(--teal-deep)", letterSpacing: "-0.02em" }}>{s.big}</div>
                <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 6, fontWeight: 500 }}>{s.lbl}</div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </section>
  </>
  );
}
