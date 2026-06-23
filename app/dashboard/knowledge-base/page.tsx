"use client"

import { Button, Flex, Input, Typography, Card, Row, Col, Segmented, Modal, Spin, Divider } from 'antd'
import { useState, useEffect } from 'react'
import { Globe, FileText, Type, Upload, X } from 'lucide-react'
import AgentList from "../../components/ui/AgentList";
import useAxios from '../../hooks/useAxios'
import type { Agent } from "../../components/ui/type";
import { useStore } from "../../hooks/useStore";
import { useRouter } from 'next/navigation'
import { Empty} from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import Loader from '@/app/components/provider/Loder';
import { marked } from "marked";
import { getCookie } from "../../config/cookies";


const { Text, Title } = Typography
const { TextArea } = Input

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};


export default function KnowledgeBasePage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<'url' | 'pdf' | 'text'>('url')
  const [url, setUrl] = useState('')
  const [textContent, setTextContent] = useState('')
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [request,,loading] = useAxios<unknown, Record<string, unknown> | FormData>({ endpoint: "KNOWLEDGEBASE",showSuccessMsg: true })
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST" });
  const[agentlist,agentlistres] = useAxios<any>({endpoint:"GET_LIST"})

  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewItem, setPreviewItem] = useState<any>(null);
  const [previewTab, setPreviewTab] = useState<'original' | 'parsed'>('original');
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [parsedText, setParsedText] = useState<string>("");
  const [parsedUrl, setParsedUrl] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);

  const sourcesList = Array.isArray(agentlistres)
    ? agentlistres
    : Array.isArray(agentlistres?.data)
      ? agentlistres.data
      : Array.isArray(agentlistres?.data?.sources)
        ? agentlistres.data.sources
        : Array.isArray(agentlistres?.data?.kbs)
          ? agentlistres.data.kbs
          : Array.isArray(agentlistres?.sources)
            ? agentlistres.sources
            : Array.isArray(agentlistres?.kbs)
              ? agentlistres.kbs
              : [];

  useEffect(() => {
    console.log("KNOWLEDGEBASE API RESPONSE:", agentlistres);
  }, [agentlistres]);

  const handleOpenPreview = async (item: any) => {
    setPreviewItem(item);
    setPreviewVisible(true);
    setPreviewTab(item.s3_path ? 'original' : 'parsed');
    setPreviewUrl("");
    setParsedText("");
    setParsedUrl("");
    setPreviewLoading(true);

    try {
      const token = getCookie("AUTH_TOKEN");
      const kbId = item.id || item.kb_id;

      // 1. Fetch Original Document as blob via backend proxy
      if (item.s3_path && kbId) {
        const fetchUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL}/files/${kbId}/preview`;
        const res = await fetch(fetchUrl, {
          headers: {
            Authorization: `Bearer ${token}`
          }
        });
        if (res.ok) {
          const blob = await res.blob();
          const bUrl = URL.createObjectURL(blob);
          setPreviewUrl(bUrl);
        } else {
          console.error("Failed to fetch original file preview, status:", res.status);
        }
      }

      // 2. Fetch Parsed Content from backend and construct local HTML blob url
      if (item.parsed_path && kbId) {
        const fetchUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL}/files/${kbId}/content`;
        const res = await fetch(fetchUrl, {
          headers: {
            Authorization: `Bearer ${token}`
          }
        });
        if (res.ok) {
          const data = await res.json();
          const rawText = data.content || data.text || (typeof data === "string" ? data : "");
          
          if (rawText) {
            const isHtml = /<[a-z][\s\S]*>/i.test(rawText);
            const htmlContent = isHtml 
              ? rawText 
              : (typeof marked === 'function' ? (marked as any)(rawText) : (marked as any).parse(rawText));
            
            const styledHtml = `
              <!DOCTYPE html>
              <html>
                <head>
                  <meta charset="utf-8">
                  <style>
                    body {
                      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                      padding: 24px;
                      color: #1f2937;
                      line-height: 1.6;
                    }
                    pre {
                      background: #f3f4f6;
                      padding: 12px;
                      border-radius: 8px;
                      overflow-x: auto;
                    }
                    code {
                      font-family: monospace;
                    }
                  </style>
                </head>
                <body>
                  ${htmlContent}
                </body>
              </html>
            `;

            const parsedBlob = new Blob([styledHtml], { type: "text/html" });
            const parsedBlobUrl = URL.createObjectURL(parsedBlob);
            setParsedUrl(parsedBlobUrl);
            setParsedText(rawText);
          }
        } else {
          console.error("Failed to fetch parsed content, status:", res.status);
        }
      }
    } catch (err) {
      console.error("Preview loading error:", err);
    } finally {
      setPreviewLoading(false);
    }
  };

  const tabs = [
    { value: 'url' as const, label: <Flex align="center" gap={6}><Globe size={14} /> URL</Flex> },
    { value: 'pdf' as const, label: <Flex align="center" gap={6}><FileText size={14} /> Docs</Flex> },
    { value: 'text' as const, label: <Flex align="center" gap={6}><Type size={14} /> Text</Flex> },
  ]

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  // ─── Persistence Logic ──────────────────────────────────────────────────────
  useEffect(() => {
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])


  async function handleSubmit() {
    if (!agent?.id) {
      alert("No agent selected")
      return
    }

    if (activeTab === 'url') {
      await request({ data: { agent_id: agent.id, agent_name: agent.name, url }, path: `/${agent.id}/sources/url` })
      await agentlist({
        path: `/agents/${agent.id}?limit=50&offset=0`,
      });
      setUrl('')
      return
    }

    if (activeTab === 'pdf') {
      if (!selectedFile) { console.warn("No file selected"); return }
      const formData = new FormData()
      formData.append('agent_id', agent.id)
      formData.append('agent_name', agent.name)
      formData.append('file', selectedFile)
      await request({ data: formData, path: `/${agent.id}/sources/pdf`, isFormData: true, transformRequest: [(data: unknown) => data] })
      await agentlist({
        path: `/agents/${agent.id}?limit=50&offset=0`,
      });
      setSelectedFile(null)
      
      
      return
    }

    if (activeTab === 'text') {
      await request({ data: { agent_id: agent.id, agent_name: agent.name, text: textContent }, path: `/${agent.id}/sources` })
      await agentlist({
        path: `/agents/${agent.id}?limit=50&offset=0`,
      });
      setTextContent('')
    }
  }

  const modalTabs = [];
  if (previewItem?.s3_path) {
    modalTabs.push({ value: 'original', label: 'Original Document' });
  }
  if (previewItem?.parsed_path) {
    modalTabs.push({ value: 'parsed', label: 'Extracted Text (Parsed)' });
  }

  return (
    <>
   {loading && <Loader />}  
    <div className="w-full min-h-screen p-4 sm:p-6 md:p-10" style={{ background: 'transparent' }}>
      <Flex vertical gap={24}>
        
        {/* Header Section */}
        <Row justify="space-between" align="middle" gutter={[16, 16]}>
          <Col xs={24} md={16}>
            <Title level={1} style={{ color: 'var(--app-text)', margin: 0, fontSize: 'calc(1.8rem + 1vw)', fontWeight: 700 }}>
              Knowledge Base
            </Title>
            <Text style={{ color: 'var(--app-text-muted)', fontSize: 16, marginTop: 4, display: 'block' }}>
              Upload and manage data sources for your artificial intelligence bots
            </Text>
          </Col>
          <Col xs={24} md={8}>
            {/* Handled dynamic alignment cleanly using Tailwind layout utilities instead of strict props */}
            <div className="flex flex-wrap items-center gap-3 justify-start md:justify-end">
              
              <Button
                style={{ 
                  border: '1px solid var(--app-border)', 
                  color: 'var(--app-text-muted)', 
                  background: 'var(--app-surface)', 
                  borderRadius: 8,
                  height: 33
                }}
                onClick={() => router.push("/dashboard/graph")}
              >
                View Graph
              </Button>
            </div>
          </Col>
        </Row>

        {/* Dynamic Context Banner */}
        <div 
          style={{ 
            background: 'var(--app-surface)', 
            border: '1px solid var(--app-border)', 
            borderRadius: 12, 
            padding: '16px 20px',
            transition: 'all 0.3s ease'
          }}
        >
          <Flex align="center" gap={16} wrap>
            <div style={{ 
              width: 42, 
              height: 42, 
              background: 'var(--app-active-bg)', 
              border: '1px solid var(--app-border)', 
              borderRadius: 10, 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center', 
              flexShrink: 0 
            }}>
              <FileText size={18} color="var(--app-primary)" />
            </div>
            <div className='flex gap-2'>
              <Text style={{ color: 'var(--app-text-muted)', fontSize: 16, display: 'block' }}>
                Adding sources to:{' '}
                <span style={{ color: agent?.name ? 'var(--app-primary)' : 'var(--app-text-soft)', fontWeight: 600 }}>
                  {/* {agent?.name ?? 'No Agent Selected'} */}
                </span>
              </Text>
              {/* <Text style={{ color: 'var(--app-text-soft)', fontSize: 13, marginTop: 2, display: 'block' }}>
                0 sources loaded
              </Text> */}
              <AgentList
              
                selectedId={agent?.id}
                onChange={(id: string, name: string) => { console.log("selected agent", id);
                setAgent({ id, name });agentlist({path : `/agents/${id}?limit=50&offset=0`})}}
              />
            </div>
          </Flex>
        </div>

        {/* Input Sandbox Container */}
        <Card 
          bordered 
          style={{ 
            background: 'var(--app-surface)', 
            borderColor: 'var(--app-border)', 
            borderRadius: 12 
          }}
          styles={{ body: { padding: '24px' } }}
        >
          <Flex vertical gap={20}>
            {/* Native Tab Alternative via AntD Segmented */}
            <div className="w-full overflow-x-auto no-scrollbar pb-1">
          <Segmented
            options={tabs}
            value={activeTab}
            onChange={(value) => setActiveTab(value as 'url' | 'pdf' | 'text')}
            style={{
              background: 'var(--app-surface-muted)',
              border: '1px solid var(--app-border)',
              padding: 4,
              borderRadius: 8,
              whiteSpace: 'nowrap', // 👈 Prevents text from breaking into lines
            }}
          />
        </div>

            {/* Dynamic Content Views */}
            <div className="w-full mt-2">
              {/* URL Capture Area */}
              {activeTab === 'url' && (
                /* Swapped "width" property out for Tailwind "w-full" assignment */
                <Row gutter={[12, 12]} className="w-full">
                  <Col xs={24} sm={18} md={20}>
                    <input
                      type="text"
                      value={url}
                      onChange={(e) => setUrl(e.target.value)}
                      placeholder="https://docs.example.com"
                      style={{ 
                        width: '100%',
                        background: 'var(--app-surface-muted)', 
                        border: '1px solid var(--app-border)', 
                        color: 'var(--app-text)', 
                        fontSize: 15, 
                        padding: '10px 14px', 
                        borderRadius: 8, 
                        outline: 'none',
                        height: 42
                      }}
                    />
                  </Col>
                  <Col xs={24} sm={6} md={4}>
                    <Button
                      type="primary"
                      icon={<Upload size={15} />}
                      onClick={handleSubmit}
                      style={{ 
                        background: 'var(--app-primary)', 
                        color: 'var(--app-on-primary)', 
                        fontWeight: 600, 
                        borderRadius: 8, 
                        height: 42,
                        width: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                        border: 'none'
                      }}
                    >
                      Crawl
                    </Button>
                  </Col>
                </Row>
              )}

              {/* PDF Document Processor */}
              {activeTab === 'pdf' && (
                <Flex vertical gap={16}>
                  {selectedFile ? (
                    <div 
                      style={{ 
                        border: '1px solid var(--app-border)', 
                        borderRadius: 8, 
                        padding: '14px 18px', 
                        background: 'var(--app-surface-muted)' 
                      }}
                    >
                      <Flex align="center" justify="space-between" wrap gap={12}>
                        <Flex align="center" gap={12}>
                          <FileText size={18} color="var(--app-primary)" />
                          <div>
                            <Text style={{ color: 'var(--app-text)', fontSize: 15, display: 'block', fontWeight: 500 }}>
                              {selectedFile.name}
                            </Text>
                            <Text style={{ color: 'var(--app-text-soft)', fontSize: 13 }}>
                              {(selectedFile.size / 1024).toFixed(1)} KB
                            </Text>
                          </div>
                        </Flex>
                        <Button 
                          type="text"
                          icon={<X size={16} />} 
                          onClick={() => setSelectedFile(null)} 
                          style={{ color: 'var(--app-text-soft)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                        />
                      </Flex>
                    </div>
                  ) : (
                    <div
                      style={{ 
                        border: '2px dashed var(--app-border)', 
                        borderRadius: 8, 
                        padding: '40px 20px', 
                        display: 'flex', 
                        flexDirection: 'column', 
                        alignItems: 'center', 
                        justifyContent: 'center', 
                        gap: 12, 
                        cursor: 'pointer', 
                        background: 'transparent',
                        transition: 'border-color 0.2s ease'
                      }}
                      onClick={() => document.getElementById('pdf-input')?.click()}
                      className="hover:border-[var(--app-primary)]"
                    >
                      <Upload size={32} color="var(--app-primary)" />
                      <Text style={{ color: 'var(--app-text-muted)', fontSize: 15, textAlign: 'center' }}>
                        Click or drag to upload PDF,Excel, CSV
                      </Text>
                    </div>
                  )}

                  <input
                    id="pdf-input"
                    type="file"
                    accept=".pdf,.txt,.md,.csv,.json"
                    style={{ display: 'none' }}
                    onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                  />

                  <Button
                    type="primary"
                    icon={<Upload size={15} />}
                    onClick={handleSubmit}
                    disabled={!selectedFile}
                    style={{ 
                      background: selectedFile ? 'var(--app-primary)' : 'var(--app-border)', 
                      color: selectedFile ? 'var(--app-on-primary)' : 'var(--app-text-soft)', 
                      fontWeight: 600, 
                      borderRadius: 8, 
                      height: 42,
                      padding: '0 24px',
                      width: 'fit-content',
                      border: 'none',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6
                    }}
                  >
                    Upload 
                  </Button>
                </Flex>
              )}

              {/* Raw Text Input Processor */}
              {activeTab === 'text' && (
                <Flex vertical gap={16}>
                  <TextArea
                    value={textContent}
                    onChange={(e) => setTextContent(e.target.value)}
                    placeholder="Paste structural or raw text updates directly into this workspace..."
                    rows={6}
                    style={{ 
                      background: 'var(--app-surface-muted)', 
                      border: '1px solid var(--app-border)', 
                      color: 'var(--app-text)', 
                      fontSize: 15, 
                      borderRadius: 8, 
                      padding: '12px',
                      resize: 'vertical' 
                    }}
                  />
                  <Button
                    type="primary"
                    icon={<Upload size={15} />}
                    onClick={handleSubmit}
                    style={{ 
                      background: 'var(--app-primary)', 
                      color: 'var(--app-on-primary)', 
                      fontWeight: 600, 
                      borderRadius: 8, 
                      height: 42,
                      padding: '0 24px',
                      width: 'fit-content',
                      border: 'none',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6
                    }}
                  >
                    Process
                  </Button>
                </Flex>
              )}
            </div>
          </Flex>
        </Card>

        {/* Data Sources Overview Table Section */}
        <Card 
          bordered 
          style={{ 
            background: 'var(--app-surface)', 
            borderColor: 'var(--app-border)', 
            borderRadius: 12,
            overflow: 'hidden'
          }}
          styles={{ body: { padding: 0 } }}
        >
          <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--app-border)' }}>
            <Text strong style={{ color: 'var(--app-text)', fontSize: 16 }}>
              Data Sources
            </Text>
          </div>
          {/* <div style={{ padding: '60px 20px', textAlign: 'center' }}>
            <Text style={{ color: 'var(--app-text-muted)', fontSize: 15, display: 'block', maxWidth: 400, margin: '0 auto' }}>
              No alternative data streams mounted to this configuration yet. Try submitting context details above.
            </Text>
          </div> */}
          
          <div className="grid gap-3">
            {
            !sourcesList?.length &&
                <Card>
                  <Empty description="No Knowledge Base Found" />
                </Card>
            }
          {sourcesList.map((item : any, index : any) => (
            <Card
              key={index}
              size="small"
              className="shadow-sm hover:shadow-md transition-all"
            >
              <div className="flex items-start gap-3 justify-between">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <FileTextOutlined
                    style={{ fontSize: 20 }}
                    className="text-blue-500 mt-1"
                  />

                  <div className="flex-1 min-w-0">
                    <Text strong className="block break-words text-[var(--app-text)]">
                      {item.name || item.source}
                    </Text>

                    <Text type="secondary" style={{ fontSize: '11px', display: 'block', marginTop: 4 }}>
                      {dayjs(item.created_at).format(
                        "DD MMM YYYY hh:mm A"
                      )}
                    </Text>
                  </div>
                </div>

                <div className="shrink-0 ml-3">
                  <Button
                    type="primary"
                    size="middle"
                    onClick={() => handleOpenPreview(item)}
                    style={{ borderRadius: 6, fontSize: 12, background: "#285d91", borderColor: "#285d91" }}
                  >
                    Open
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
            </Card>

      </Flex>
    </div>

    <Modal
      title={
        <Flex align="center" justify="space-between" style={{ width: '90%' }}>
          <span className="font-extrabold text-sm text-[var(--app-text)] truncate" style={{ maxWidth: '300px' }}>
            {previewItem?.name || previewItem?.source || "Document Preview"}
          </span>
          {modalTabs.length > 1 && (
            <Segmented
              options={modalTabs}
              value={previewTab}
              onChange={(val) => setPreviewTab(val as 'original' | 'parsed')}
              size="small"
            />
          )}
        </Flex>
      }
      open={previewVisible}
      onCancel={() => {
        setPreviewVisible(false);
        if (previewUrl && previewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(previewUrl);
        }
        setPreviewUrl("");
        setParsedText("");
        setParsedUrl("");
        setPreviewItem(null);
      }}
      footer={null}
      width={1200}
      styles={{
        body: { padding: 12, height: "70vh", display: "flex", flexDirection: "column", background: "var(--app-surface-muted)" }
      }}
    >
      {previewLoading ? (
        <Flex vertical align="center" justify="center" gap={12} className="h-full my-auto">
          <Spin size="large" />
          <Text className="text-xs text-[var(--app-text-soft)] font-semibold">
            Loading preview content...
          </Text>
        </Flex>
      ) : (
        <div className="flex-1 w-full bg-[var(--app-surface)] rounded-xl border border-[var(--app-border)]/40 overflow-hidden relative shadow-sm h-full">
          {previewTab === 'parsed' ? (
            <div className="w-full h-full overflow-hidden">
              {parsedUrl ? (
                <Flex gap={2} className="h-full" style={{ height: "100%" }}>
                  <div className="w-full h-full overflow-hidden">
                    <iframe
                      src={previewUrl ? `${previewUrl}#navpanes=0` : ""}
                      width="100%"
                      height="100%"
                      style={{ border: "none" }}
                    />
                  </div>
                  <Divider type='vertical' style={{ height: '100%', margin: 0 }}/>
                  <div className="w-full h-full overflow-hidden">
                    <iframe
                      src={parsedUrl}
                      width="100%"
                      height="100%"
                      style={{ border: "none" }}
                    />
                  </div>
                </Flex>
              ) : (
                <div
                  className="w-full h-full overflow-y-auto p-6 markdown-content custom-scrollbar text-[var(--app-text)]"
                  dangerouslySetInnerHTML={{
                    __html: parsedText
                      ? (typeof marked === 'function' ? (marked as any)(parsedText) : (marked as any).parse(parsedText))
                      : "<p style='color: var(--app-text-muted)'>No extracted text content available.</p>"
                  }}
                />
              )}
            </div>
          ) : (
            <div className="w-full h-full flex flex-col justify-start overflow-hidden">
              {previewUrl ? (
                <iframe
                  src={`${previewUrl}#navpanes=0`}
                  width="100%"
                  height="100%"
                  style={{ border: "none" }}
                />
              ) : (
                <Flex vertical align="center" justify="center" className="h-full text-neutral-400">
                  <span className="text-xs">Preview URL not available</span>
                </Flex>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
    </>
  )
}
