"use client";
import React, { useEffect, useRef, useState } from "react";
import { Button, Space, Tag, Typography } from "antd";
import { heroRotationItems } from "../lib/content";

const { Title, Text, Paragraph } = Typography;

const TYPE_SPEED_MS = 38;
const ANSWER_DELAY_MS = 350;
const CYCLE_PAUSE_MS = 3600;
const INITIAL_DELAY_MS = 2200;

export default function Hero() {
  const [query, setQuery] = useState(heroRotationItems[0].q);
  const [answerHtml, setAnswerHtml] = useState(heroRotationItems[0].a);
  const [source, setSource] = useState(heroRotationItems[0].s);
  const [tags, setTags] = useState<string[]>(heroRotationItems[0].tags);
  const [visible, setVisible] = useState(true);

  const indexRef = useRef(0);
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion) return;

    const clearAll = () => {
      timeoutsRef.current.forEach((t) => clearTimeout(t));
      timeoutsRef.current = [];
    };

    const typeIn = (text: string, onDone: () => void) => {
      let n = 0;
      const iv = setInterval(() => {
        n += 1;
        setQuery(text.slice(0, n));
        if (n >= text.length) {
          clearInterval(iv);
          onDone();
        }
      }, TYPE_SPEED_MS);
    };

    const cycle = () => {
      const item = heroRotationItems[indexRef.current];
      setVisible(false);
      typeIn(item.q, () => {
        const t = setTimeout(() => {
          setAnswerHtml(item.a);
          setSource(item.s);
          setTags(item.tags);
          setVisible(true);
          indexRef.current = (indexRef.current + 1) % heroRotationItems.length;
          const next = setTimeout(cycle, CYCLE_PAUSE_MS);
          timeoutsRef.current.push(next);
        }, ANSWER_DELAY_MS);
        timeoutsRef.current.push(t);
      });
    };

    const initial = setTimeout(cycle, INITIAL_DELAY_MS);
    timeoutsRef.current.push(initial);

    return clearAll;
  }, []);

  return (
    <header className="gs-hero">
      <div className="wrap">
        <Title
          level={1}
          style={{
            fontSize: "clamp(34px,5vw,56px)",
            fontWeight: 800,
            maxWidth: 830,
            margin: "0 auto",
            letterSpacing: "-0.03em",
            textAlign: "center",
          }}
        >
          Every answer your team needs,{" "}
          <span style={{ color: "var(--teal-deep)" }}>connected</span> across every tool you use.
        </Title>

        <Paragraph
          style={{
            fontSize: 19,
            color: "var(--muted)",
            maxWidth: 620,
            margin: "22px auto 30px",
            textAlign: "center",
          }}
        >
          Gsearch finds the answer across all your apps, connects the dots between them, and helps
          your team act on it — instantly.
        </Paragraph>

        <Space size={14} wrap style={{ justifyContent: "center", display: "flex" }}>
          <Button
            type="primary"
            size="large"
            href="#cta"
            style={{
              background: "var(--teal)",
              borderColor: "var(--teal)",
              fontWeight: 700,
              borderRadius: 11,
              boxShadow: "0 6px 18px -6px rgba(15,181,161,0.5)",
            }}
          >
            Book a demo
          </Button>
          <Button
            size="large"
            href="#"
            style={{
              borderColor: "var(--line-2)",
              color: "var(--ink)",
              fontWeight: 700,
              borderRadius: 11,
            }}
          >
            Start for free
          </Button>
        </Space>

        <div className="gs-ratings">
          <span className="r">
            <Text strong style={{ color: "var(--ink)" }}>G2</Text>{" "}
            <span className="stars" style={{ color: "var(--gold)" }}>★★★★★</span>{" "}
            <Text style={{ color: "var(--muted)", fontSize: 14, fontWeight: 600 }}>4.7</Text>
          </span>
          <span className="r">
            <Text strong style={{ color: "var(--ink)" }}>Capterra</Text>{" "}
            <span className="stars" style={{ color: "var(--gold)" }}>★★★★★</span>{" "}
            <Text style={{ color: "var(--muted)", fontSize: 14, fontWeight: 600 }}>5.0</Text>
          </span>
        </div>

        <div className="gs-gradient-stage" aria-hidden="true">
          <div className="gs-search-card">
            <div className="gs-search-bar">
              <span className="si">⌕</span>
              <span className="txt">
                {query}
                <span className="cur">|</span>
              </span>
            </div>
            <div
              className="gs-answer-card"
              style={{ opacity: visible ? 1 : 0, transition: "opacity .25s" }}
            >
              <div className="ac-top">
                <Tag
                  color="var(--teal)"
                  style={{ fontWeight: 700, fontSize: 11.5, borderRadius: 7 }}
                >
                  AI answer
                </Tag>
                <Text style={{ fontSize: 12, color: "var(--faint)", fontWeight: 600 }}>
                  {source}
                </Text>
              </div>
              <p dangerouslySetInnerHTML={{ __html: answerHtml }} />
              <div className="gs-answer-tags">
                {tags.map((tag) => (
                  <Tag
                    key={tag}
                    style={{
                      color: "var(--teal-deep)",
                      background: "var(--teal-soft)",
                      borderColor: "transparent",
                      fontWeight: 600,
                      borderRadius: 8,
                    }}
                  >
                    {tag}
                  </Tag>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
