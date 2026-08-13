"use client";

import { useEffect } from "react";

export default function ScrollReveal() {
  useEffect(() => {
    // Single shared IntersectionObserver instance
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("active");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.05,
        rootMargin: "0px 0px -40px 0px",
      }
    );

    const scanAndObserve = () => {
      const revealElements = document.querySelectorAll(".reveal:not(.active)");
      revealElements.forEach((el) => {
        observer.observe(el);
      });
    };

    // Initial scan
    scanAndObserve();

    // Re-scan periodically & on scroll to ensure every section gets animated
    const interval = setInterval(scanAndObserve, 600);
    window.addEventListener("scroll", scanAndObserve, { passive: true });
    window.addEventListener("resize", scanAndObserve, { passive: true });

    return () => {
      clearInterval(interval);
      window.removeEventListener("scroll", scanAndObserve);
      window.removeEventListener("resize", scanAndObserve);
      observer.disconnect();
    };
  }, []);

  return null;
}
