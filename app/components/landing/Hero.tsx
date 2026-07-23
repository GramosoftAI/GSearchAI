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
  const [isSearching, setIsSearching] = useState(false);

  const indexRef = useRef(0);
  const timeoutsRef = useRef<any[]>([]);

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion) return;

    const clearAll = () => {
      timeoutsRef.current.forEach((t) => {
        clearTimeout(t);
        clearInterval(t);
      });
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
      timeoutsRef.current.push(iv);
    };

    const typeInAnswer = (text: string, onDone: () => void) => {
      let currentText = "";
      let index = 0;
      const iv = setInterval(() => {
        if (index >= text.length) {
          clearInterval(iv);
          onDone();
          return;
        }

        // HTML-safe tag insertion: append the full tag instantly to prevent rendering broken tags
        if (text[index] === "<") {
          const closingIndex = text.indexOf(">", index);
          if (closingIndex !== -1) {
            currentText += text.slice(index, closingIndex + 1);
            index = closingIndex + 1;
          } else {
            currentText += text[index];
            index++;
          }
        } else {
          currentText += text[index];
          index++;
        }

        setAnswerHtml(currentText);
      }, 15); // Slightly faster typing rate for answer text
      timeoutsRef.current.push(iv);
    };

    const cycle = () => {
      const item = heroRotationItems[indexRef.current];
      setIsSearching(true);
      setAnswerHtml("");
      setSource("");
      setTags([]);

      typeIn(item.q, () => {
        const t = setTimeout(() => {
          setIsSearching(false);
          
          typeInAnswer(item.a, () => {
            // Display source citations and tags only after the answer typing has finished
            setSource(item.s);
            setTags(item.tags);
            
            indexRef.current = (indexRef.current + 1) % heroRotationItems.length;
            const next = setTimeout(cycle, CYCLE_PAUSE_MS);
            timeoutsRef.current.push(next);
          });
        }, 800); // Wait in searching state before writing the answer
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
            color:"var(--ink)"
          }}
        >
          Meet your company's{" "}
          <span style={{ color: "var(--teal-deep)" }}>second brain.</span>
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
          Gsearch connects every tool your team uses, remembers how everything relates, and answers any question instantly — so your team stops searching and starts knowing.
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
              padding:25
            }}
          >
            Book a demo
          </Button>
          <Button
            type="text"
            size="large"
            href="register"
            style={{
              borderColor: "var(--line-2)",
              color: "var(--ink)",
              fontWeight: 700,
              borderRadius: 11,
              padding:25
            }}
          >
            Start for free
          </Button>
        </Space>

        {/* <div className="gs-ratings">
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
        </div> */}

        <div className="gs-gradient-stage" aria-hidden="true">
          <div className="gs-search-card">
            <div className="gs-search-bar">
              <span className="si">⌕</span>
              <span className="txt">
                {query}
                <span className="cur">|</span>
              </span>
            </div>
            <div className="gs-answer-card">
              <div className="ac-top">
                <span className="pill-ai">AI answer</span>
                <span style={{ fontSize: 12, color: "var(--faint)", fontWeight: 600 }}>
                  {isSearching ? "" : source}
                </span>
              </div>
              {isSearching ? (
                <div className="gs-searching">
                  Searching
                  <span className="sd">
                    <i></i>
                    <i></i>
                    <i></i>
                  </span>
                </div>
              ) : (
                <>
                  <p dangerouslySetInnerHTML={{ __html: answerHtml }} />
                  <div className="gs-answer-tags">
                    {tags.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
