import type { Metadata } from "next";
import "@/app/home/style.css";
import Navbar from "@/app/components/landing/Navbar";
import Footer from "@/app/components/landing/Footer";
import PrivacyPolicy from "@/components/PrivacyPolicy";

export const metadata: Metadata = {
  title: "GSearchAI Privacy Policy | Slack & Google Drive Third-Party Data Handling",
  description:
    "GSearchAI Privacy Policy details how we collect, use, process, store, and protect third-party data from Slack, Google Drive, and workplace connectors, including data retention and deletion procedures.",
  alternates: {
    canonical: "https://gsearchai.com/privacy-policy",
  },
  openGraph: {
    title: "GSearchAI Privacy Policy | Slack & Google Drive Third-Party Data Handling",
    description:
      "GSearchAI Privacy Policy details how we collect, use, process, store, and protect third-party data from Slack, Google Drive, and workplace connectors, including data retention and deletion procedures.",
    url: "https://gsearchai.com/privacy-policy",
    siteName: "GSearchAI",
    type: "website",
  },
};

export default function PrivacyPolicyPage() {
  return (
    <main className="min-h-screen bg-white">
      <Navbar />
      <PrivacyPolicy />
      <Footer />
    </main>
  );
}
