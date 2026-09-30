import type { Metadata } from "next";
import SupportPageContent from "./SupportPageContent";

export const metadata: Metadata = {
  title: "GSearchAI App Support & Help Center | Slack & Enterprise Search",
  description:
    "Get responsive customer support for GSearchAI and our Slack application. Direct email assistance and ticket form without requiring sign-in or account creation. Guaranteed response within 2 business days.",
  alternates: {
    canonical: "https://gsearchai.com/support",
  },
  openGraph: {
    title: "GSearchAI App Support & Help Center",
    description:
      "Get responsive customer support for GSearchAI and our Slack application without creating an account. Direct email and webform support.",
    url: "https://gsearchai.com/support",
    siteName: "GSearchAI",
    type: "website",
  },
};

export default function SupportPage() {
  return (
    <main>
      <SupportPageContent />
    </main>
  );
}
