import type { Metadata } from "next";
import "@/app/home/style.css";
import Navbar from "@/app/components/landing/Navbar";
import Footer from "@/app/components/landing/Footer";
import SecurityPolicy from "@/components/SecurityPolicy";

export const metadata: Metadata = {
    title: "GSearchAI Vulnerability Disclosure Program (VDP) & Security Policy",
    description:
        "GSearchAI Vulnerability Disclosure Program guidelines covering our Slack application, APIs, and enterprise search platform. Learn about our scope, reporting guidelines, and Safe Harbor.",
    alternates: {
        canonical: "https://gsearchai.com/security",
    },
    openGraph: {
        title: "GSearchAI Vulnerability Disclosure Program (VDP) & Security Policy",
        description:
            "GSearchAI Vulnerability Disclosure Program guidelines covering our Slack application, APIs, and enterprise search platform.",
        url: "https://gsearchai.com/security",
        siteName: "GSearchAI",
        type: "website",
    },
};

export default function SecurityPage() {
    return (
        <main className="min-h-screen bg-white">
            <Navbar />
            <SecurityPolicy />
            <Footer />
        </main>
    );
}
