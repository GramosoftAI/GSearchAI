import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Geist_Mono } from "next/font/google";
import "./globals.css";
import GlobalProvider from "./components/provider/GlobalProvider";
import { Toaster } from "react-hot-toast";
import { AntdRegistry } from "@ant-design/nextjs-registry";

const plusJakartaSans = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Gsearch — Your company's second brain. AI search across every tool your team uses.",
  description: "Gsearch connects every tool your team uses, remembers how everything relates, and answers any question instantly — so your team stops searching and starts knowing.",
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
    >
      <body className="min-h-full ">
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
