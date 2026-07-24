"use client";

import { Flex, App } from "antd";
import EmbedScriptSection from "./EmbedScriptSection";
import ChannelsSection from "./ChannelsSection";

function IntegrationsContent() {
  return (
    <div className="w-full max-w-7xl mx-auto p-3 md:p-10 animate-in fade-in duration-500">
      <Flex vertical gap={40}>
        {/* Top/Embed Script Section */}
        <EmbedScriptSection />

        {/* Bottom/Available Channels Section */}
        <ChannelsSection />

        {/* Ecosystem Banner */}
        <div className="p-8 md:p-12 bg-gradient-to-br from-[#0fb5a1] via-[#0a8576] to-[#065047] rounded-3xl text-white shadow-lg overflow-hidden relative">
          <div className="absolute -top-24 -right-24 w-72 h-72 bg-blue-400/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-24 -left-24 w-72 h-72 bg-emerald-400/5 rounded-full blur-3xl pointer-events-none" />
          
          <Flex justify="space-between" align="center" className="w-full flex-col md:flex-row gap-6 relative z-10">
            <div className="space-y-1.5 text-center md:text-left max-w-xl">
              <h3 className="m-0 text-white font-bold text-xl md:text-2xl tracking-tight">
                Need a Custom Connection?
              </h3>
              <span className="text-blue-100 text-sm md:text-base block font-normal leading-relaxed">
                Our core architects design personalized system schemas and custom API loops built for scaled architectures.
              </span>
            </div>
            <button 
              className="w-full md:w-auto h-12 px-8 rounded-xl bg-white text-[#0fb5a1] border-none font-semibold transition-transform active:scale-95 flex items-center justify-center flex-row-reverse gap-2 cursor-pointer"
            >
              Contact Support
            </button>
          </Flex>
        </div>
      </Flex>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          height: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: var(--app-border, #e2e8f0);
          border-radius: 99px;
        }
      `}</style>
    </div>
  );
}

export default function IntegrationsPage() {
  return (
    <App>
      <IntegrationsContent />
    </App>
  );
}
