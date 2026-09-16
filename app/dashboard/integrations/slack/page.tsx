"use client";

import { App, Button } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import SlackIntegrationSettings from "../SlackIntegrationSettings";

function SlackIntegrationPageContent() {
  const router = useRouter();

  return (
    <div className="w-full max-w-7xl mx-auto p-3 md:p-10 animate-in fade-in duration-500">
      <div className="mb-6 flex items-center justify-between">
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => router.push("/dashboard/integrations")}
          className="text-xs md:text-sm font-semibold text-[var(--app-text-soft)] hover:text-[#0fb5a1] flex items-center gap-2 p-0 h-auto cursor-pointer"
        >
          Back to Integrations
        </Button>
      </div>

      <SlackIntegrationSettings />
    </div>
  );
}

export default function SlackIntegrationPage() {
  return (
    <App>
      <SlackIntegrationPageContent />
    </App>
  );
}
