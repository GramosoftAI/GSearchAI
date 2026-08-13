"use client";
import { useMemo, useState } from "react";
import { Slider, Typography} from "antd";

const { Title, Paragraph, Text } = Typography;

const RECOVERY_RATE = 0.35;

const formatNumber = (n: number): string => n.toLocaleString("en-US");

export default function RoiCalculator() {
  const [people, setPeople] = useState(50);
  const [hours, setHours] = useState(5);

  const weeklyHoursReclaimed = useMemo(
    () => Math.round(people * hours * RECOVERY_RATE),
    [people, hours]
  );
  const yearlyHoursReclaimed = useMemo(
    () => weeklyHoursReclaimed * 52,
    [weeklyHoursReclaimed]
  );

  return (
    <section className="gs-block alt">
      <div className="wrap">
        <div className="gs-sec-center">
          <div className="gs-eyebrow">What it&apos;s worth to you</div>
          <Title level={2} className="gs-sec-h" style={{color:"var(--ink)",fontWeight:800}}>See the time your team gets back.</Title>
          <Paragraph className="gs-sec-lede" style={{fontSize:"18px",paddingBottom:10,color:"var(--muted)"}}>
            Knowledge workers lose hours every week just looking for information. Move the
            slider to see what Gsearch could give back.
          </Paragraph>
        </div>

        <div className="gs-roi">
          <div className="gs-roi-controls">
            <label style={{ display: "block", fontWeight: 700, color: "var(--ink)", fontSize: 15, margin: "0 0 8px" }}>
              Team size:{" "}
              <Text style={{ color: "var(--teal-deep)", fontWeight: 700 }}>{people}</Text>{" "}
              people
            </label>
            <Slider
              min={5}
              max={500}
              step={5}
              value={people}
              onChange={(v) => setPeople(v as number)}
              tooltip={{ formatter: (v) => `${v} people` }}
              styles={{ track: { background: "var(--teal)" }, handle: { borderColor: "var(--teal)" } }}
            />

            <label style={{ display: "block", fontWeight: 700, color: "var(--ink)", fontSize: 15, margin: "16px 0 8px" }}>
              Hours each person loses searching per week:{" "}
              <Text style={{ color: "var(--teal-deep)", fontWeight: 700 }}>{hours}</Text>
            </label>
            <Slider
              min={1}
              max={12}
              step={1}
              value={hours}
              onChange={(v) => setHours(v as number)}
              tooltip={{ formatter: (v) => `${v} hrs` }}
              styles={{ track: { background: "var(--teal)" }, handle: { borderColor: "var(--teal)" } }}
            />

            <Paragraph style={{ fontSize: 15, color: "var(--muted)", marginTop: 4 }}>
              Gsearch typically gives back around a third of that time by returning a direct,
              connected answer instead of a hunt across tools.
            </Paragraph>
          </div>

          <div className="gs-roi-out">
            <div style={{ fontSize: 46, fontWeight: 800, color: "var(--teal-deep)", letterSpacing: "-0.03em", lineHeight: 1 }}>
              {formatNumber(weeklyHoursReclaimed)}
            </div>
            <div style={{ fontSize: 14.5, color: "var(--body)", marginTop: 8, fontWeight: 600 }}>hours reclaimed every week</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
              That&apos;s about <Text strong style={{ color: "var(--ink)" }}>{formatNumber(yearlyHoursReclaimed)}</Text> hours a year your
              team spends on real work instead of searching.
            </div>
          </div>
        </div>

        <Paragraph style={{ textAlign: "center", fontSize: 12.5, color: "var(--faint)", marginTop: 18 }}>
          Illustrative estimate based on your inputs and a 35% time-recovery assumption. Your
          results will vary.
        </Paragraph>
      </div>
    </section>
  );
}
