"use client";
import React from "react";
import { Row, Col, Divider, Typography } from "antd";
import BrandGlyph from "./BrandGlyph";

const { Title, Paragraph, Link } = Typography;

const footerColumns = [
  {
    title: "Product",
    links: [
      { label: "Enterprise search", href: "#product" },
      { label: "AI assistant", href: "#" },
      { label: "Agents & workflows", href: "#" },
      { label: "Integrations", href: "#connectors" },
    ],
  },
  {
    title: "Solutions",
    links: [
      { label: "Support", href: "#teams" },
      { label: "Sales", href: "#teams" },
      { label: "Engineering", href: "#teams" },
      { label: "HR", href: "#teams" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "How it works", href: "#how" },
      { label: "Documentation", href: "#" },
      { label: "Blog", href: "#" },
      { label: "Help center", href: "#" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About Gramosoft", href: "#" },
      { label: "Security", href: "#security" },
      { label: "Book a demo", href: "#cta" },
      { label: "Contact", href: "#" },
    ],
  },
];

export default function Footer() {
  const handleScroll = (e: React.MouseEvent, href: string) => {
    if (href.startsWith("#")) {
      e.preventDefault();
      const targetId = href.substring(1);
      if (targetId) {
        const element = document.getElementById(targetId);
        if (element) {
          element.scrollIntoView({ behavior: "smooth" });
        }
      } else {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
  };

  return (
  <footer className="gs-footer">
    <div className="wrap">
      <Row gutter={[36, 36]}>
        <Col xs={24} md={6} style={{ flex: "0 0 calc(100%/5*1.5)" }}>
          <div className="gs-foot-brand">
            <a
              href="#"
              className="gs-brand"
              onClick={(e) => handleScroll(e, "#")}
            >
              <BrandGlyph />
              Gsearch
            </a>
            <Paragraph style={{ fontSize: 14, color: "var(--muted)", maxWidth: 240, marginTop: 14 }}>
              Your company&apos;s second brain — AI search connected across every tool your team uses. A Gramosoft product.
            </Paragraph>
          </div>
        </Col>

        {footerColumns.map((col) => (
          <Col xs={12} md={4} key={col.title} className="gs-foot-col">
            <Title level={5} style={{ fontSize: 13, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 16, fontWeight: 700 }}>
              {col.title}
            </Title>
            {col.links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={(e) => handleScroll(e, link.href)}
                style={{ display: "block", fontSize: 14.5, color: "var(--body)", marginBottom: 11, fontWeight: 500 }}
              >
                {link.label}
              </Link>
            ))}
          </Col>
        ))}
      </Row>

      <Divider style={{ borderColor: "var(--line)", marginTop: 46 }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13.5, color: "var(--faint)" }}>
        <span>© 2026 Gramosoft Private Limited</span>
        <span>All systems operational</span>
      </div>
    </div>
  </footer>
  );
}
