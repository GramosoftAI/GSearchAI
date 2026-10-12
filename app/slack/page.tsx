import type { Metadata } from "next";
import SlackLandingContent from "./SlackLandingContent";

export const metadata: Metadata = {
  title: "GSearchAI for Slack | Enterprise AI Knowledge Search & Assistant",
  description:
    "Empower your Slack workspace with GSearchAI. Connect Google Drive, Notion, Confluence, and Jira to search company documents and receive instant citation-backed answers directly in Slack channels.",
  alternates: {
    canonical: "https://gsearchai.com/slack",
  },
  openGraph: {
    title: "GSearchAI for Slack | Enterprise AI Knowledge Search & Assistant",
    description:
      "Empower your Slack workspace with GSearchAI. Connect Google Drive, Notion, Confluence, and Jira to search company documents and receive instant citation-backed answers directly in Slack channels.",
    url: "https://gsearchai.com/slack",
    siteName: "GSearchAI",
    images: [
      {
        url: "/512_512.png",
        width: 512,
        height: 512,
        alt: "GSearchAI for Slack",
      },
    ],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "GSearchAI for Slack | Enterprise AI Knowledge Search & Assistant",
    description:
      "Search across Google Drive, Notion, Confluence, and Jira without leaving Slack.",
    images: ["/512_512.png"],
  },
};

export default function SlackLandingPage() {
  return (
    <main>
      <SlackLandingContent />
    </main>
  );
}
