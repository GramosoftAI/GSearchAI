import Navbar from "../components/landing/Navbar";
import Hero from "../components/landing/Hero";
import LogoStrip from "../components/landing/LogoStrip";
import FeatureTrio from "../components/landing/FeatureTrio";
import HowItWorks from "../components/landing/HowItWorks";
import SoloVsWorkspace from "../components/landing/SoloVsWorkspace";
import Connectors from "../components/landing/Connectors";
import CapabilityTabs from "../components/landing/CapabilityTabs";
import SearchComparison from "../components/landing/SearchComparison";
import Industries from "../components/landing/Industries";
import UseCases from "../components/landing/UseCases";
import TimeToValueAndTestimonial from "../components/landing/TimeToValueAndTestimonial";
import RoiCalculator from "../components/landing/RoiCalculator";
import Security from "../components/landing/Security";
import TeamSwitcher from "../components/landing/TeamSwitcher";
import Faq from "../components/landing/Faq";
import KeyTakeawaysAndSources from "../components/landing/KeyTakeawaysAndSources";
import FinalCta from "../components/landing/FinalCta";
import Footer from "../components/landing/Footer";
import ScrollReveal from "../components/landing/ScrollReveal";
import "./style.css"

export default function HomePage() {
  return (
    <>
      <ScrollReveal />
      <Navbar />
      <article className="gs-landing-article">
        <div className="fade-in-up"><Hero /></div>
        <LogoStrip />
        <div className="reveal"><FeatureTrio /></div>
        <div className="reveal"><HowItWorks /></div>
        <div className="reveal"><SoloVsWorkspace /></div>
        <div className="reveal"><Connectors /></div>
        <div className="reveal"><CapabilityTabs /></div>
        <div className="reveal"><SearchComparison /></div>
        <div className="reveal"><Industries /></div>
        {/* <div className="reveal"><UseCases /></div> */}
        {/* <div className="reveal"><TimeToValueAndTestimonial /></div> */}
       
        <div className="reveal"><TeamSwitcher /></div>
        <div className="reveal"><RoiCalculator /></div>
        <div className="reveal"><Faq /></div>
        <div className="reveal"><KeyTakeawaysAndSources /></div>
        <div className="reveal"><FinalCta /></div>
      </article>
      <Footer />
    </>
  );
}
