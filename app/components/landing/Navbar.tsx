"use client";
import React, { useState} from "react";
import { Button, Drawer } from "antd";
import { MenuOutlined, GithubOutlined } from "@ant-design/icons";
import BrandGlyph from "./BrandGlyph";
import { useRouter } from "next/navigation";
import { useGithubStars } from "../provider/GithubStarsProvider";

const navLinks = [
  { href: "#product", label: "Product" },
  { href: "#teams", label: "Solution" },
  { href: "#how", label: "How it works" },
  { href: "#paths", label: "Pricing" },
  { href: "#connectors", label: "Integrations" },
  { href: "#security", label: "Security" },
  { href: "#faq", label: "FAQ" },
];

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const stars = useGithubStars();

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
    <nav className="gs-nav">
      <div className="wrap gs-nav-inner">
        <a
          href="#"
          className="gs-brand"
          onClick={(e) => handleScroll(e, "#")}
        >
          <BrandGlyph height={36} />
        </a>

        <div className="gs-nav-links">
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              onClick={(e) => handleScroll(e, link.href)}
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="gs-nav-cta">

          <a
            href="https://github.com/GramosoftAI/GRAGAI"
            target="_blank"
            rel="noopener noreferrer"
            className="gs-github-star"
          >
            <GithubOutlined style={{ fontSize: "16px" }} />
            <span>Star</span>
            <span className="gs-github-star-divider"></span>
            <span className="gs-github-star-count">{stars}</span>
          </a>
          <Button
            // type="text"
            className="signin"
            href="/login"
            style={{ fontWeight: 600, color: "var(--body)", padding: 10 }}
          >
            Log in
          </Button>

          {/* <Button
            type="text"
            href="/register"
            style={{ borderColor: "var(--line-2)", color: "var(--ink)", fontWeight: 700, borderRadius: 11, padding: 20 }}
          >
            Start free
          </Button> */}
          {/* <Button
            type="primary"
            href="#cta"
            style={{ background: "var(--teal)", borderColor: "var(--teal)", fontWeight: 700, borderRadius: 11,padding:20 }}
          >
            Book a demo
          </Button> */}
        </div>

        {/* Mobile menu button */}
        <div className="gs-menu-btn">
          <Button
            aria-label="Menu"
            icon={<MenuOutlined />}
            onClick={() => setOpen(true)}
            style={{ border: "1.5px solid var(--line-2)", borderRadius: 9, fontWeight: 700 }}
          >
            Menu
          </Button>
        </div>
      </div>

      <Drawer
        title={
          <span className="gs-brand">
            <BrandGlyph height={32} />
          </span>
        }
        placement="right"
        onClose={() => setOpen(false)}
        open={open}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              onClick={(e) => {
                handleScroll(e, link.href);
                setOpen(false);
              }}
              style={{ fontSize: 16, fontWeight: 600, color: "var(--body)" }}
            >
              {link.label}
            </a>
          ))}
          <hr style={{ border: "none", borderTop: "1px solid var(--line)", margin: "8px 0" }} />
          <div className="gs-drawer-github-wrapper">
            <a
              href="https://github.com/GramosoftAI/GRAGAI"
              target="_blank"
              rel="noopener noreferrer"
              className="gs-github-star"
              onClick={() => setOpen(false)}
            >
              <GithubOutlined style={{ fontSize: "16px" }} />
              <span>Star on GitHub</span>
              <span className="gs-github-star-divider"></span>
              <span className="gs-github-star-count">{stars}</span>
            </a>
          </div>
          <Button
            type="text"
            href="/login"
            onClick={() => setOpen(false)}
            style={{ textAlign: "left", fontWeight: 600, color: "var(--body)", padding: 0 }}
          >
            Log in
          </Button>
          <Button
            href="/register"
            onClick={() => setOpen(false)}
            style={{ borderColor: "var(--line-2)", color: "var(--ink)", fontWeight: 700, borderRadius: 11 }}
          >
            Start free
          </Button>
          <Button
            type="primary"
            href="#cta"
            onClick={(e) => {
              handleScroll(e, "#cta");
              setOpen(false);
            }}
            style={{ background: "var(--teal)", borderColor: "var(--teal)", fontWeight: 700, borderRadius: 11 }}
          >
            Book a demo
          </Button>
        </div>
      </Drawer>
    </nav>
  );
}
