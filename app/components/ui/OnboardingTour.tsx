"use client";

import React, { useState, useEffect, useRef } from "react";
import { Flex, Typography, Button } from "antd";
import { LuArrowRight, LuX, LuSparkles } from "react-icons/lu";

const { Text, Title } = Typography;

export interface TourStep {
  targetId: string;
  title: string;
  content: string;
  placement: "above" | "below" | "left" | "right";
}

interface OnboardingTourProps {
  steps: TourStep[];
  activeStep: number;
  isActive: boolean;
  onStepChange: (stepIndex: number) => void;
  onClose: () => void;
}

export default function OnboardingTour({
  steps,
  activeStep,
  isActive,
  onStepChange,
  onClose,
}: OnboardingTourProps) {
  const [mounted, setMounted] = useState(false);
  const [targetRect, setTargetRect] = useState<DOMRect | null>(null);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({
    position: "fixed",
    width: "320px",
    opacity: 0,
    pointerEvents: "none",
  });
  const [arrowStyle, setArrowStyle] = useState<React.CSSProperties>({});
  
  const popoverRef = useRef<HTMLDivElement>(null);
  const step = steps[activeStep];

  useEffect(() => {
    setMounted(true);
  }, []);

  
  useEffect(() => {
    if (!isActive || !mounted || !step) {
      setTargetRect(null);
      return;
    }

    const updateRect = () => {
      const el = document.getElementById(step.targetId);
      if (el) {
        const rect = el.getBoundingClientRect();
        
        setTargetRect((prev) => {
          if (
            prev &&
            prev.top === rect.top &&
            prev.left === rect.left &&
            prev.width === rect.width &&
            prev.height === rect.height
          ) {
            return prev;
          }
          return rect;
        });
      } else {
       
        setTargetRect(null);
      }
    };

    updateRect();
    const interval = setInterval(updateRect, 250);
    window.addEventListener("resize", updateRect);
    window.addEventListener("scroll", updateRect, { capture: true });

    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", updateRect);
      window.removeEventListener("scroll", updateRect, { capture: true });
    };
  }, [isActive, mounted, step, activeStep]);

  useEffect(() => {
    if (!targetRect || !step || !popoverRef.current) return;

    const popoverWidth = 320;
    const popoverHeight = popoverRef.current.getBoundingClientRect().height || 180;
    const offset = 16;

    const targetCenterX = targetRect.left + targetRect.width / 2;
    const targetCenterY = targetRect.top + targetRect.height / 2;

    let top = 0;
    let left = targetCenterX - popoverWidth / 2;
    let arrowDir: "up" | "down" | "left" | "right" = "up";

    switch (step.placement) {
      case "above":
        top = targetRect.top - popoverHeight - offset;
        arrowDir = "down";
        break;
      case "below":
        top = targetRect.bottom + offset;
        arrowDir = "up";
        break;
      case "left":
        left = targetRect.left - popoverWidth - offset;
        top = targetCenterY - popoverHeight / 2;
        arrowDir = "right";
        break;
      case "right":
        left = targetRect.right + offset;
        top = targetCenterY - popoverHeight / 2;
        arrowDir = "left";
        break;
    }

    const padding = 16;
    if (left < padding) {
      left = padding;
    } else if (left + popoverWidth > window.innerWidth - padding) {
      left = window.innerWidth - popoverWidth - padding;
    }

    if (top < padding) {
      top = padding;
    } else if (top + popoverHeight > window.innerHeight - padding) {
      top = window.innerHeight - popoverHeight - padding;
    }

    
    let arrowLeft: React.CSSProperties["left"] = "50%";
    let arrowTop: React.CSSProperties["top"] = "auto";
    let arrowRight: React.CSSProperties["right"] = "auto";
    let arrowBottom: React.CSSProperties["bottom"] = "auto";

    if (arrowDir === "up" || arrowDir === "down") {
      const calculatedArrowLeft = targetCenterX - left;
      const arrowPadding = 24;
      arrowLeft = Math.max(arrowPadding, Math.min(popoverWidth - arrowPadding, calculatedArrowLeft));
      if (arrowDir === "up") {
        arrowTop = -6;
        arrowBottom = "auto";
      } else {
        arrowTop = "auto";
        arrowBottom = -6;
      }
    } else {
      const calculatedArrowTop = targetCenterY - top;
      const arrowPadding = 24;
      arrowTop = Math.max(arrowPadding, Math.min(popoverHeight - arrowPadding, calculatedArrowTop));
      if (arrowDir === "left") {
        arrowLeft = -6;
        arrowRight = "auto";
      } else {
        arrowLeft = "auto";
        arrowRight = -6;
      }
    }

    setPopoverStyle({
      position: "fixed",
      top: `${top}px`,
      left: `${left}px`,
      width: `${popoverWidth}px`,
      zIndex: 99999,
      opacity: 1,
      pointerEvents: "auto",
      transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
    });

    setArrowStyle({
      position: "absolute",
      left: typeof arrowLeft === "number" ? `${arrowLeft}px` : arrowLeft,
      top: typeof arrowTop === "number" ? `${arrowTop}px` : arrowTop,
      right: typeof arrowRight === "number" ? `${arrowRight}px` : arrowRight,
      bottom: typeof arrowBottom === "number" ? `${arrowBottom}px` : arrowBottom,
      width: "12px",
      height: "12px",
      transform: "rotate(45deg)",
      backgroundColor: "var(--app-surface)",
      borderLeft: arrowDir === "left" || arrowDir === "up" ? "1px solid var(--app-border)" : "none",
      borderTop: arrowDir === "up" || arrowDir === "right" ? "1px solid var(--app-border)" : "none",
      borderRight: arrowDir === "right" || arrowDir === "down" ? "1px solid var(--app-border)" : "none",
      borderBottom: arrowDir === "down" || arrowDir === "left" ? "1px solid var(--app-border)" : "none",
      zIndex: -1,
      boxShadow: "inherit",
    });
  }, [targetRect, step, activeStep]);

  if (!isActive || !mounted || !step) return null;

 
  const renderBackdrops = () => {
    if (!targetRect) {
      
      return (
        <div
          onClick={onClose}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100vw",
            height: "100vh",
            backgroundColor: "rgba(13, 15, 23, 0.75)",
            backdropFilter: "blur(4px)",
            zIndex: 99990,
            transition: "all 0.3s ease",
          }}
        />
      );
    }

    const t = targetRect.top;
    const l = targetRect.left;
    const h = targetRect.height;
    const w = targetRect.width;
    // const padding = 1;

    return (
      <>
        <div
          onClick={onClose}
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            width: "100vw",
            height: "100vh",
            zIndex: 99989,
            cursor: "pointer",
          }}
        />

        
        <div
          style={{
            position: "fixed",
            left: `${l}px`,
            top: `${t}px`,
            width: `${w}px`,
            height: `${h}px`,
            borderRadius: step.targetId === "tour-agent-select" ? "9999px" : step.targetId === "tour-chat-input-card" ? "24px" : "16px",
            border: "2px solid #0fb5a1",
            boxShadow: "0 0 0 9999px rgba(13, 15, 23, 0.75), 0 0 16px rgba(15, 181, 161, 0.5)",
            pointerEvents: "none",
            zIndex: 99995,
            transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />
      </>
    );
  };

  const handleNext = () => {
    if (activeStep < steps.length - 1) {
      onStepChange(activeStep + 1);
    } else {
      onClose();
    }
  };

  const handleBack = () => {
    if (activeStep > 0) {
      onStepChange(activeStep - 1);
    }
  };

  return (
    <>
      {renderBackdrops()}

     
      <div
        ref={popoverRef}
        style={popoverStyle}
        className="bg-white/95 dark:bg-[#121624]/90 backdrop-blur-lg border border-[var(--app-border)]/50 rounded-2xl p-5 shadow-2xl flex flex-col gap-3 animate-in zoom-in-95 duration-200"
      >
        <div style={arrowStyle} />

        <Flex justify="space-between" align="center" className="w-full">
          <Flex align="center" gap={6}>
            <LuSparkles className="text-[#0fb5a1] animate-bounce" size={15} />
            <Text className="text-xs font-black tracking-widest text-[#0fb5a1] dark:text-[#34d399] uppercase">
              Step {activeStep + 1} of {steps.length}
            </Text>
          </Flex>
          <Button
            type="text"
            shape="circle"
            size="small"
            icon={<LuX size={14} className="text-[var(--app-text-soft)]" />}
            onClick={onClose}
            className="hover:bg-[var(--app-hover)] flex items-center justify-center cursor-pointer border-none bg-transparent"
          />
        </Flex>

        <Flex vertical gap={4} className="w-full">
          <Title level={5} className="!m-0 !font-extrabold !text-[var(--app-text)] !text-sm">
            {step.title}
          </Title>
          <Text className="text-xs font-medium text-[var(--app-text-soft)] leading-relaxed">
            {step.content}
          </Text>
        </Flex>

        <Flex justify="space-between" align="center" className="w-full pt-2 border-t border-[var(--app-border)]/20 mt-1 shrink-0">
          <Button
            type="text"
            onClick={onClose}
            className="!text-xs !font-bold text-[var(--app-text-soft)] hover:text-red-500 !p-0 bg-transparent border-none cursor-pointer"
          >
            Skip
          </Button>

          <Flex gap={8}>
            {activeStep > 0 && (
              <Button
                size="small"
                onClick={handleBack}
                className="!text-xs !font-bold !rounded-lg border-[var(--app-border)] hover:bg-[var(--app-hover)] text-[var(--app-text-soft)] cursor-pointer"
              >
                Back
              </Button>
            )}

            <Button
              type="primary"
              size="small"
              onClick={handleNext}
              className="!text-xs !font-black !rounded-lg bg-[#0fb5a1] hover:bg-[#0da18f] text-white border-none flex items-center gap-1 cursor-pointer"
            >
              <span>{activeStep === steps.length - 1 ? "Done" : "Next"}</span>
              {activeStep < steps.length - 1 && <LuArrowRight size={12} />}
            </Button>
          </Flex>
        </Flex>
      </div>
    </>
  );
}
