import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Geist_Mono } from "next/font/google";
import "./globals.css";
import GlobalProvider from "./components/provider/GlobalProvider";
import { Toaster } from "react-hot-toast";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import Script from "next/script";
import { schema } from "./lib/schema";

const plusJakartaSans = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// export const metadata: Metadata = {
//   title: "Gsearch — Your company's second brain. AI search across every tool your team uses.",
//   description: "Gsearch connects every tool your team uses, remembers how everything relates, and answers any question instantly — so your team stops searching and starts knowing.",
// };
export const metadata: Metadata = {
  icons: {
    icon: "/512_512.png",
  },
  title:
    "Gsearch — Meet your company's second brain. AI Enterprise Search & Chat Platform",

  description:
    "Gsearch connects your tools, docs, and databases with AI search. Ask questions in plain language and get instant answers from your company data.",

  keywords: [
  "AI enterprise search",
  "company AI search tool",
  "internal knowledge search",
  "AI chatbot for company data",
  "RAG search system",
  "enterprise AI assistant",
  "ask your data AI",
  "document search AI",
  "Slack AI search",
  "Notion AI alternative",
  "Gsearch",
  "AI knowledge base search"
],

  authors: [
    {
      name: "Gramosoft Private Limited",
    },
  ],

  robots: {
    index: true,
    follow: true,
  },

  alternates: {
    canonical: "https://gramosoft.tech",
  },

  openGraph: {
    title: "Gsearch — Your Company's AI Brain for Instant Answers",
    description:
      "Search across all your company tools, documents, chats, and apps using natural language AI. Get instant, accurate answers instead of searching manually.",
    url: "https://gramosoft.tech/gsearch",
    siteName: "Gsearch by Gramosoft",
    images: [
      {
        url: "https://gramosoft.tech/images/gsearch-og.png",
      },
    ],
    locale: "en_IN",
    type: "website",
  },

  twitter: {
    card: "summary_large_image",
    title: "Gsearch — AI Search for Your Company Knowledge",
    description:
      "Ask questions across your company data and get instant AI-powered answers.",
    images: ["https://gramosoft.tech/images/gsearch-og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${plusJakartaSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full ">
         <Script
          id="schema"
            type="application/ld+json"
            dangerouslySetInnerHTML={{
              __html: JSON.stringify(schema),
            }}
          />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  const stored = localStorage.getItem('app_theme_preference');
                  const isDashboard = window.location.pathname.startsWith('/dashboard') || window.location.pathname.startsWith('/widget');
                  let theme = 'light';
                  if (isDashboard && stored === 'dark') {
                    theme = 'dark';
                  }
                  document.documentElement.setAttribute('data-theme', theme);
                  document.documentElement.style.colorScheme = theme;
                  if (theme === 'dark') {
                    document.documentElement.classList.add('dark');
                  } else {
                    document.documentElement.classList.remove('dark');
                  }
                } catch (e) {}
              })();
            `,
          }}
        />
        <AntdRegistry>
          <GlobalProvider>
            {children}
            <Toaster position="top-right"  toastOptions={{
            duration: 5000, // 3 seconds
          }}/>
          </GlobalProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
