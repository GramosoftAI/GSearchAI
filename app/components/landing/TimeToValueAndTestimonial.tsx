import React from "react";
import { Row, Col, Card, Typography, Statistic } from "antd";

const { Title, Paragraph, Text } = Typography;

const ttvItems = [
  { n: "Days", title: "From setup to answers", body: "Connect your sources and your team gets useful answers in days — not a six-month project." },
  { n: "Zero", title: "IT lift required", body: "Permissions carry over automatically. No data to move, no new system to maintain." },
  { n: "Day 1", title: "Insight from the start", body: "See what your team searches for, what they find, and where knowledge gaps are costing time." },
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
          <Title level={2} className="gs-sec-h" style={{color:"var(--ink)",fontWeight:800}}>Up and running in days, not months.</Title>
          <Paragraph className="gs-sec-lede" style={{fontSize:"18px",paddingBottom:10,color:"var(--muted)"}}>
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
                <Title level={3} style={{ fontSize: 18, margin: "10px 0 8px",color:"var(--ink)",fontWeight:700 }}>{item.title}</Title>
                <Paragraph style={{ fontSize: 14.5, color: "var(--muted)", margin: 0 }}>{item.body}</Paragraph>
              </div>
            </Col>
          ))}
        </Row>

        <div className="gs-testi" style={{ marginTop: 40 }}>
          <div>
            <Paragraph style={{ fontSize: 24, fontWeight: 700, color: "var(--ink)", lineHeight: 1.32, letterSpacing: "-0.02em" }}>
              &quot;Before Gsearch, our knowledge lived in too many places and people spent too much time searching. Now it&apos;s like the whole company <Text style={{ color: "var(--teal-deep)", fontWeight: 700,fontSize:24 }}>shares one memory.</Text>&quot;
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
                <div style={{ fontSize: 14, color: "var(--muted)", marginTop: 6, fontWeight: 500 }}>{s.lbl}</div>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </section>
  </>
  );
}
