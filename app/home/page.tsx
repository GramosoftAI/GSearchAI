"use client";
import { useEffect } from "react";
import Navbar from "../components/landing/Navbar";
import Hero from "../components/landing/Hero";
import LogoStrip from "../components/landing/LogoStrip";
import FeatureTrio from "../components/landing/FeatureTrio";
import HowItWorks from "../components/landing/HowItWorks";
import Connectors from "../components/landing/Connectors";
import CapabilityTabs from "../components/landing/CapabilityTabs";
import Industries from "../components/landing/Industries";
import UseCases from "../components/landing/UseCases";
import TimeToValueAndTestimonial from "../components/landing/TimeToValueAndTestimonial";
import RoiCalculator from "../components/landing/RoiCalculator";
import Security from "../components/landing/Security";
import TeamSwitcher from "../components/landing/TeamSwitcher";
import Faq from "../components/landing/Faq";
import FinalCta from "../components/landing/FinalCta";
import Footer from "../components/landing/Footer";
import "./style.css"

export default function HomePage() {
  useEffect(() => {
    // Prevent browser auto-scroll restoration on landing page
    if ('scrollRestoration' in window.history) {
      window.history.scrollRestoration = 'manual';
    }
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    const revealElements = document.querySelectorAll(".reveal");

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("active");
            // Stop observing once visible (first-time scroll reveal only)
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.1,
        rootMargin: "0px 0px -50px 0px",
      }
    );

    revealElements.forEach((el) => {
      observer.observe(el);
    });

    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <>
      <Navbar />
      <div className="fade-in-up"><Hero /></div>
      <LogoStrip />
      <div className="reveal"><FeatureTrio /></div>
      <div className="reveal"><HowItWorks /></div>
      <div className="reveal"><Connectors /></div>
      <div className="reveal"><CapabilityTabs /></div>
      <div className="reveal"><Industries /></div>
      <div className="reveal"><UseCases /></div>
      <div className="reveal"><TimeToValueAndTestimonial /></div>
      <div className="reveal"><RoiCalculator /></div>
      <div className="reveal"><Security /></div>
      <div className="reveal"><TeamSwitcher /></div>
      <div className="reveal"><Faq /></div>
      <div className="reveal"><FinalCta /></div>
      <Footer />
    </>
  );
}
