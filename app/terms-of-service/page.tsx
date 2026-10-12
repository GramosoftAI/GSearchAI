import type { Metadata } from "next";
import "@/app/home/style.css";
import Navbar from "@/app/components/landing/Navbar";
import Footer from "@/app/components/landing/Footer";
import TermsOfService from "@/components/TermsOfService";

export const metadata: Metadata = {
  title: "GSearchAI Terms of Service",
  description:
    "GSearchAI Terms of Service govern your access to and use of the GSearchAI platform, website, applications, and third-party integrations provided by Gramosoft Private Limited.",
  alternates: {
    canonical: "https://gsearchai.com/terms-of-service",
  },
  openGraph: {
    title: "GSearchAI Terms of Service",
    description:
      "GSearchAI Terms of Service govern your access to and use of the GSearchAI platform, website, applications, and third-party integrations provided by Gramosoft Private Limited.",
    url: "https://gsearchai.com/terms-of-service",
    siteName: "GSearchAI",
    type: "website",
  },
};

export default function TermsOfServicePage() {
  return (
    <main className="min-h-screen bg-white">
      <Navbar />
      <TermsOfService />
      <Footer />
    </main>
  );
}
