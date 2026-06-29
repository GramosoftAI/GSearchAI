"use client"

import { Button, Flex, Input, Typography, Card, Row, Col, Segmented, Modal, Spin, Divider, Progress, message } from 'antd'
import { useState, useEffect, useRef } from 'react'
import { Globe, FileText, Type, Upload, X, Image as ImageIcon } from 'lucide-react'
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
import { toast } from "react-hot-toast";

// Allowed file types for knowledge base uploads
const ALLOWED_EXTENSIONS = ['.pdf', '.csv', '.xls', '.xlsx', '.png', '.jpg', '.jpeg', '.gif', '.webp'];

function getFileExtension(fileName: string): string {
  const idx = fileName.lastIndexOf('.');
  return idx >= 0 ? fileName.slice(idx).toLowerCase() : '';
}

function validateFileType(file: File): boolean {
  return ALLOWED_EXTENSIONS.includes(getFileExtension(file.name));
}

const { Text, Title } = Typography
const { TextArea } = Input

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};


function parsePythonDict(str: string): any {
  let i = 0;
  const len = str.length;

  function skipWhitespace() {
    while (i < len && /\s/.test(str[i])) {
      i++;
    }
  }

  function parseValue(): any {
    skipWhitespace();
    if (i >= len) return null;

    const char = str[i];

    // Parse String
    if (char === "'" || char === '"') {
      const quoteChar = char;
      i++; // skip quote
      let val = "";
      while (i < len) {
        if (str[i] === "\\") {
          i++;
          if (i < len) {
            const nextChar = str[i];
            if (nextChar === "n") val += "\n";
            else if (nextChar === "t") val += "\t";
            else if (nextChar === "r") val += "\r";
            else if (nextChar === "b") val += "\b";
            else if (nextChar === "f") val += "\f";
            else val += nextChar;
            i++;
          }
        } else if (str[i] === quoteChar) {
          i++; // skip close quote
          return val;
        } else {
          val += str[i];
          i++;
        }
      }
      return val;
    }

    // Parse Object / Dict
    if (char === "{") {
      i++; // skip '{'
      const obj: any = {};
      while (i < len) {
        skipWhitespace();
        if (str[i] === "}") {
          i++;
          return obj;
        }
        const key = parseValue();
        skipWhitespace();
        if (str[i] !== ":") {
          return obj;
        }
        i++; // skip ':'
        const val = parseValue();
        obj[key] = val;
        skipWhitespace();
        if (str[i] === ",") {
          i++; // skip ','
        }
      }
      return obj;
    }

    // Parse List
    if (char === "[") {
      i++; // skip '['
      const arr: any[] = [];
      while (i < len) {
        skipWhitespace();
        if (str[i] === "]") {
          i++;
          return arr;
        }
        const val = parseValue();
        arr.push(val);
        skipWhitespace();
        if (str[i] === ",") {
          i++; // skip ','
        }
      }
      return arr;
    }

    // Parse True, False, None, or numbers
    let word = "";
    while (i < len && /[a-zA-Z0-9_\.\+-]/.test(str[i])) {
      word += str[i];
      i++;
    }

    if (word === "True") return true;
    if (word === "False") return false;
    if (word === "None") return null;

    const num = Number(word);
    if (!isNaN(num)) return num;

    return word;
  }

  try {
    return parseValue();
  } catch (e) {
    console.error("Failed to parse Python dict:", e);
    return null;
  }
}

function cleanExtractedText(raw: string): string {
  if (!raw) return "";
  
  let processed = raw.trim();
  
  if (processed.startsWith("{") && processed.endsWith("}")) {
    try {
      const parsed = JSON.parse(processed);
      if (parsed) {
        processed = parsed.markdown || parsed.text || parsed.content || processed;
      }
    } catch (jsonErr) {
      try {
        const parsed = parsePythonDict(processed);
        if (parsed) {
          processed = parsed.markdown || parsed.text || parsed.content || processed;
        }
      } catch (pyErr) {
        console.error("Failed to parse as Python dict:", pyErr);
      }
    }
  }

  if (typeof processed !== "string") {
    processed = String(processed);
  }

  processed = processed
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/\\r/g, "\r")
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"');

  return processed;
}

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

  const activeJobs = useStore((state) => state.activeJobs);
  const setActiveJobs = useStore((state) => state.setActiveJobs);
  
  const activeJobsRef = useRef(activeJobs);
  useEffect(() => {
    activeJobsRef.current = activeJobs;
  }, [activeJobs]);

  useEffect(() => {
    if (activeJobs.length === 0) return;

    const token = getCookie("AUTH_TOKEN");
    
    const interval = setInterval(async () => {
      const currentJobs = activeJobsRef.current;
      for (const job of currentJobs) {
        if (job.progress >= 100 || ['completed', 'finished', 'success', 'failed', 'error'].includes(job.status)) {
          continue;
        }

        try {
          const fetchUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL}/jobs/${job.id}`;
          const res = await fetch(fetchUrl, {
            headers: {
              Authorization: `Bearer ${token}`
            }
          });
          
          if (!res.ok) {
            console.error(`Error polling job ${job.id}:`, res.status);
            continue;
          }
          
          const data = await res.json();
          const jobObj = data?.job || data?.data?.job || data?.result?.job || data?.data || data?.result || data;

          const rawStatus = jobObj?.status || "";
          const status = rawStatus.toLowerCase();
          
          let rawProgress = jobObj?.progress ?? jobObj?.process ?? jobObj?.percentage ?? jobObj?.percent ?? 0;
          
          if (rawProgress && typeof rawProgress === 'object') {
            const obj = rawProgress as any;
            rawProgress = obj.progress ?? obj.process ?? obj.percentage ?? obj.percent ?? obj.value ?? obj.current ?? 0;
          }

          if (typeof rawProgress === 'string') {
            rawProgress = parseFloat(rawProgress.replace(/[^0-9.]/g, '')) || 0;
          }
          
          if (rawProgress > 0 && rawProgress <= 1.0) {
            rawProgress = rawProgress * 100;
          }
          const progress = isNaN(rawProgress) ? 0 : Math.min(100, Math.max(0, Math.round(rawProgress)));
          const timeRemaining = jobObj?.time_remaining || jobObj?.estimated_time || data?.time_remaining || data?.estimated_time;
          const currentStep = jobObj?.current_step || data?.current_step || jobObj?.currentStep || data?.currentStep;
          const startedAt = jobObj?.started_at || data?.started_at || jobObj?.startedAt || data?.startedAt;

          setActiveJobs(prev => prev.map(j => {
            if (j.id === job.id) {
              return {
                ...j,
                progress: progress,
                status: status || 'running',
                timeRemaining: timeRemaining ? String(timeRemaining) : undefined,
                current_step: currentStep ? String(currentStep) : undefined,
                started_at: startedAt ? String(startedAt) : undefined
              };
            }
            return j;
          }));

          if (status === 'finished' || status === 'completed' || status === 'success' || progress >= 100) {
            toast.success(`Ingestion completed for: ${job.name}`);
            
            setTimeout(() => {
              setActiveJobs(prev => prev.filter(j => j.id !== job.id));
            }, 3000);

            if (agent?.id) {
              agentlist({
                path: `/agents/${agent.id}?limit=50&offset=0`,
              });
            }
          } else if (status === 'failed' || status === 'error') {
            toast.error(`Ingestion failed for: ${job.name}`);
            
            setTimeout(() => {
              setActiveJobs(prev => prev.filter(j => j.id !== job.id));
            }, 5000);
          }

        } catch (err) {
          console.error(`Failed polling job ${job.id}:`, err);
        }
      }
    }, 13000);

    return () => clearInterval(interval);
  }, [activeJobs.length, agent?.id]);

  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewItem, setPreviewItem] = useState<any>(null);
  const [previewTab, setPreviewTab] = useState<'original' | 'parsed'>('original');
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [parsedText, setParsedText] = useState<string>("");
  const [parsedUrl, setParsedUrl] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewType, setPreviewType] = useState<string>("other");
  const [excelSheets, setExcelSheets] = useState<{ [sheetName: string]: string[][] }>({});
  const [excelSheetNames, setExcelSheetNames] = useState<string[]>([]);
  const [activeExcelSheet, setActiveExcelSheet] = useState<string>("");

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
    setPreviewUrl("");
    setParsedText("");
    setParsedUrl("");
    setPreviewType("other");
    setExcelSheets({});
    setExcelSheetNames([]);
    setActiveExcelSheet("");

    const nameStr = (item.name || item.source || "").toLowerCase();
    const isUrl = nameStr.includes("url") || nameStr.includes("http") || nameStr.includes("www.");

    const kbId = item.id || item.kb_id;

    if (isUrl) {
      setPreviewLoading(false);
      setPreviewTab('parsed');
      
      const rawSource = item.name || item.source || "";
      let extractedUrl = "";
      const urlMatch = rawSource.match(/(https?:\/\/[^\s]+)/i);
      if (urlMatch) {
        extractedUrl = urlMatch[1];
      } else {
        const domainMatch = rawSource.match(/([a-zA-Z0-9-]+\.[a-zA-Z]{2,}[^\s]*)/);
        if (domainMatch) {
          extractedUrl = "https://" + domainMatch[1];
        } else {
          extractedUrl = rawSource;
        }
      }

      if (extractedUrl) {
        window.open(extractedUrl, '_blank');
      }

      setParsedText(`### URL Source\n\nDestination URL opened in a new tab:\n\n**URL:** [${extractedUrl}](${extractedUrl})\n\nNo preview content available. Data is empty.`);
      return;
    }

    // Set initial tab based on name and paths
    const isText = nameStr.includes("text");
    const isPdf = nameStr.endsWith(".pdf");
    if (isPdf && (isText || (item.parsed_path && !item.s3_path))) {
      setPreviewTab('parsed');
    } else {
      setPreviewTab('original');
    }

    setPreviewLoading(true);

    try {
      const token = getCookie("AUTH_TOKEN");

      // 1. Fetch Original Document as blob via backend proxy if s3_path exists
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

          const contentType = blob.type.toLowerCase();
          const isPDF = contentType.includes("pdf") || nameStr.endsWith(".pdf");
          const isImage = contentType.includes("image/") || nameStr.endsWith(".png") || nameStr.endsWith(".jpg") || nameStr.endsWith(".jpeg") || nameStr.endsWith(".webp") || nameStr.endsWith(".gif");
          const isCSV = contentType.includes("csv") || nameStr.endsWith(".csv");
          const isExcel = contentType.includes("excel") || contentType.includes("spreadsheet") ||
            contentType.includes("vnd.ms-excel") || contentType.includes("vnd.openxmlformats-officedocument.spreadsheetml.sheet") ||
            nameStr.endsWith(".xls") || nameStr.endsWith(".xlsx");

          if (isPDF) {
            setPreviewType("pdf");
          } else if (isImage) {
            setPreviewType("image");
          } else if (isCSV || isExcel) {
            setPreviewType(isCSV ? "csv" : "excel");
            const arrayBuffer = await blob.arrayBuffer();
            const XLSX = await import("xlsx");
            const workbook = XLSX.read(arrayBuffer, { type: "array" });

            const sheetsData: { [sheetName: string]: string[][] } = {};
            workbook.SheetNames.forEach((sheetName) => {
              const worksheet = workbook.Sheets[sheetName];
              const jsonData = XLSX.utils.sheet_to_json<any[]>(worksheet, { header: 1 });
              sheetsData[sheetName] = jsonData.map((row: any) =>
                Array.isArray(row)
                  ? row.map((cell) => (cell !== null && cell !== undefined ? String(cell) : ""))
                  : []
              );
            });

            setExcelSheets(sheetsData);
            setExcelSheetNames(workbook.SheetNames);
            if (workbook.SheetNames.length > 0) {
              setActiveExcelSheet(workbook.SheetNames[0]);
            }
          }
        } else {
          console.error("Failed to fetch original file preview, status:", res.status);
        }
      }

      // 2. Fetch Parsed Content from backend if parsed_path exists and is a PDF
      if (isPdf && item.parsed_path && kbId) {
        const fetchUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL}/files/${kbId}/content`;
        const res = await fetch(fetchUrl, {
          headers: {
            Authorization: `Bearer ${token}`
          }
        });
        if (res.ok) {
          const data = await res.json();
          const rawText = data.content || data.text || (typeof data === "string" ? data : "");
          const cleanedText = cleanExtractedText(rawText);
          
          if (cleanedText) {
            const isHtml = /<[a-z][\s\S]*>/i.test(cleanedText);
            const htmlContent = isHtml 
              ? cleanedText 
              : (typeof marked === 'function' ? (marked as any)(cleanedText) : (marked as any).parse(cleanedText));
            
            const styledHtml = `
              <!DOCTYPE html>
              <html>
                <head>
                  <meta charset="utf-8">
                  <style>
                    html, body {
                      margin: 0;
                      padding: 0;
                      width: 100%;
                      height: 100%;
                      overflow: auto;
                    }
                    body {
                      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                      padding: 16px;
                      color: #1f2937;
                      line-height: 1.6;
                      box-sizing: border-box;
                    }
                    h1 {
                      font-size: 1.8em;
                      margin-top: 24px;
                      margin-bottom: 16px;
                      font-weight: 600;
                      line-height: 1.25;
                      border-bottom: 1px solid #eaecef;
                      padding-bottom: 0.3em;
                    }
                    h2 {
                      font-size: 1.4em;
                      margin-top: 24px;
                      margin-bottom: 16px;
                      font-weight: 600;
                      line-height: 1.25;
                      border-bottom: 1px solid #eaecef;
                      padding-bottom: 0.3em;
                    }
                    h3 {
                      font-size: 1.2em;
                      margin-top: 24px;
                      margin-bottom: 16px;
                      font-weight: 600;
                      line-height: 1.25;
                    }
                    table {
                      border-collapse: collapse;
                      min-width: max-content;
                      width: max-content;
                      table-layout: auto;
                      margin-bottom: 16px;
                    }
                    table table {
                      min-width: 100%;
                      width: 100%;
                    }
                    th, td {
                      border: 1px solid #dcdcdc;
                      padding: 8px;
                      white-space: nowrap;
                      vertical-align: top;
                    }
                    thead th {
                      position: sticky;
                      top: 0;
                      background: white;
                      z-index: 10;
                      border-bottom: 2px solid #dcdcdc;
                    }
                    img {
                      max-width: 100%;
                      height: auto;
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
            setParsedText(cleanedText);
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

  const handleDeleteSource = (item: any) => {
    const kbId = item.id || item.kb_id;
    if (!kbId) {
      toast.error("Source ID not found");
      return;
    }

    Modal.confirm({
      title: 'Delete Data Source',
      content: `Are you sure you want to delete "${item.name || item.source}"? This action cannot be undone.`,
      okText: 'Delete',
      okType: 'danger',
      cancelText: 'Cancel',
      onOk: async () => {
        try {
          const token = getCookie("AUTH_TOKEN");
          const fetchUrl = `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${kbId}`;
          const res = await fetch(fetchUrl, {
            method: 'DELETE',
            headers: {
              'Accept': 'application/json',
              'Authorization': `Bearer ${token}`
            }
          });

          if (res.ok) {
            toast.success("Data source deleted successfully");
            if (agent?.id) {
              await agentlist({
                path: `/agents/${agent.id}?limit=50&offset=0`,
              });
            }
          } else {
            const errData = await res.json().catch(() => ({}));
            toast.error(errData.message || "Failed to delete data source");
          }
        } catch (err) {
          console.error("Delete error:", err);
          toast.error("An error occurred while deleting the data source");
        }
      }
    });
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
      message.warning("No agent selected")
      return
    }

    if (activeTab === 'url') {
      const res = await request({ data: { agent_id: agent.id, agent_name: agent.name, url }, path: `/${agent.id}/sources/url` }) as any
      const jobId = res?.jobId || res?.job_id || res?.data?.jobId || res?.data?.job_id || res?.result?.jobId || res?.result?.job_id;
      if (jobId) {
        setActiveJobs(prev => [...prev, {
          id: jobId,
          name: url,
          type: 'url',
          progress: 0,
          status: 'pending'
        }]);
      }
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
      const res = await request({ data: formData, path: `/${agent.id}/sources/pdf`, isFormData: true, transformRequest: [(data: unknown) => data] }) as any
      const jobId = res?.jobId || res?.job_id || res?.data?.jobId || res?.data?.job_id || res?.result?.jobId || res?.result?.job_id;
      if (jobId) {
        setActiveJobs(prev => [...prev, {
          id: jobId,
          name: selectedFile.name,
          type: 'pdf',
          progress: 0,
          status: 'pending'
        }]);
      }
      await agentlist({
        path: `/agents/${agent.id}?limit=50&offset=0`,
      });
      setSelectedFile(null)
      return
    }

    if (activeTab === 'text') {
      const res = await request({ data: { agent_id: agent.id, agent_name: agent.name, text: textContent }, path: `/${agent.id}/sources` }) as any
      const jobId = res?.jobId || res?.job_id || res?.data?.jobId || res?.data?.job_id || res?.result?.jobId || res?.result?.job_id;
      if (jobId) {
        setActiveJobs(prev => [...prev, {
          id: jobId,
          name: textContent.slice(0, 30) + (textContent.length > 30 ? '...' : ''),
          type: 'text',
          progress: 0,
          status: 'pending'
        }]);
      }
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
  const previewItemName = (previewItem?.name || previewItem?.source || "").toLowerCase();
  const isPdfFile = previewItemName.endsWith(".pdf");
  if (previewItem?.parsed_path && isPdfFile) {
    modalTabs.push({ value: 'parsed', label: 'Extracted Text' });
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
                      <span className="inline sm:hidden md:hidden lg:inline">Crawl</span>
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
                      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                      onDrop={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const file = e.dataTransfer.files?.[0];
                        if (!file) return;
                        if (!validateFileType(file)) {
                          toast.error(`Unsupported file type "${getFileExtension(file.name)}". Only PDF, Excel, CSV, and Images are allowed.`);
                          return;
                        }
                        setSelectedFile(file);
                      }}
                      className="hover:border-[var(--app-primary)]"
                    >
                      <Upload size={32} color="var(--app-primary)" />
                      <Text style={{ color: 'var(--app-text-muted)', fontSize: 15, textAlign: 'center' }}>
                        Click or drag to upload PDF, Excel, CSV, or Image
                      </Text>
                      <Text style={{ color: 'var(--app-text-soft)', fontSize: 11, textAlign: 'center' }}>
                        Supported: .pdf · .xls · .xlsx · .csv · .png · .jpg · .jpeg · .gif · .webp
                      </Text>
                    </div>
                  )}

                  <input
                    id="pdf-input"
                    type="file"
                    accept=".pdf,.csv,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.webp"
                    style={{ display: 'none' }}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      if (!validateFileType(file)) {
                        toast.error(`Unsupported file type "${getFileExtension(file.name)}". Only PDF, Excel, CSV, and Images are allowed.`);
                        e.target.value = '';
                        return;
                      }
                      setSelectedFile(file);
                    }}
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

        {/* Ingestion Progress Panel */}
        {activeJobs.length > 0 && (
          <Card
            bordered
            style={{
              background: 'linear-gradient(135deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.01))',
              borderColor: 'var(--app-border)',
              borderRadius: 12,
              backdropFilter: 'blur(10px)',
              boxShadow: '0 8px 32px 0 rgba(0, 0, 0, 0.1)'
            }}
            styles={{ body: { padding: '20px' } }}
          >
            <Flex vertical gap={16}>
              <div className="flex items-center justify-between">
                <Flex align="center" gap={8}>
                  <Spin size="small" />
                  <Text strong style={{ color: 'var(--app-text)', fontSize: 16 }}>
                    {activeJobs.map((job) => job.current_step || 'Ingesting Data Sources...').join(', ')}
                  </Text>
                </Flex>
                <Text style={{ color: 'var(--app-text-muted)', fontSize: 12 }}>
                  Start At : {activeJobs.map((job) => job.started_at ? dayjs(job.started_at).format('DD-MM-YYYY HH:mm:ss') : 'Pending').join(', ')}
                </Text>
              </div>

              <div className="grid gap-4">
                {activeJobs.map((job) => (
                  <div 
                    key={job.id} 
                    style={{ 
                      background: 'rgba(255, 255, 255, 0.02)',
                      border: '1px solid rgba(255, 255, 255, 0.05)',
                      borderRadius: 8,
                      padding: '12px 16px'
                    }}
                  >
                    <Flex vertical gap={8}>
                      <Flex align="center" justify="space-between" wrap gap={8}>
                        <Flex align="center" gap={8} className="min-w-0 flex-1">
                          {job.type === 'url' && <Globe size={16} color="var(--app-primary)" />}
                          {job.type === 'pdf' && <FileText size={16} color="var(--app-primary)" />}
                          {job.type === 'text' && <Type size={16} color="var(--app-primary)" />}
                          <Text strong className="truncate text-sm text-[var(--app-text)] flex-1">
                            {job.name}
                          </Text>
                        </Flex>
                        <Flex align="center" gap={8} className="shrink-0">
                          <span 
                            style={{ 
                              fontSize: 11, 
                              fontWeight: 600,
                              textTransform: 'uppercase',
                              letterSpacing: '0.05em',
                              padding: '2px 8px',
                              borderRadius: 12,
                              background: job.status === 'completed' || job.status === 'success' || job.status === 'finished'
                                ? 'rgba(34, 197, 94, 0.15)' 
                                : (job.status === 'failed' || job.status === 'error' ? 'rgba(239, 68, 68, 0.15)' : 'rgba(59, 130, 246, 0.15)'),
                              color: job.status === 'completed' || job.status === 'success' || job.status === 'finished'
                                ? '#4ade80' 
                                : (job.status === 'failed' || job.status === 'error' ? '#f87171' : '#60a5fa')
                            }}
                          >
                            {job.status}
                          </span>
                          <Text style={{ color: 'var(--app-text-muted)', fontSize: 13, fontWeight: 600 }}>
                            {job.progress}%
                          </Text>
                        </Flex>
                      </Flex>

                      <Progress 
                        percent={job.progress} 
                        status={
                          job.status === 'failed' || job.status === 'error' 
                            ? 'exception' 
                            : (job.status === 'completed' || job.status === 'success' || job.status === 'finished' ? 'success' : 'active')
                        }
                        strokeColor={
                          job.status === 'failed' || job.status === 'error'
                            ? '#f87171'
                            : (job.status === 'completed' || job.status === 'success' || job.status === 'finished' ? '#4ade80' : 'var(--app-primary)')
                        }
                        showInfo={false}
                        size="small"
                      />

                      {job.timeRemaining && (
                        <Text style={{ color: 'var(--app-text-soft)', fontSize: 11 }}>
                          Estimated time remaining: {job.timeRemaining}
                        </Text>
                      )}
                    </Flex>
                  </div>
                ))}
              </div>
            </Flex>
          </Card>
        )}
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

                <div className="shrink-0 ml-3 flex gap-2">
                  <Button
                    type="primary"
                    size="middle"
                    onClick={() => handleOpenPreview(item)}
                    style={{ borderRadius: 6, fontSize: 12, background: "#285d91", borderColor: "#285d91" }}
                  >
                    Open
                  </Button>
                  <Button
                    type="primary"
                    danger
                    size="middle"
                    onClick={() => handleDeleteSource(item)}
                    style={{ borderRadius: 6, fontSize: 12 }}
                  >
                    Delete
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
        <div className="py-1">
          <span className="font-extrabold text-base text-[var(--app-text)] truncate block" style={{ maxWidth: '85%' }}>
            {previewItem?.name || previewItem?.source || "Document Preview"}
          </span>
        </div>
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
      style={{ top: 20 }}
      styles={{
        body: { padding: "20px 12px 12px 12px", height: "85vh", display: "flex", flexDirection: "column", background: "var(--app-surface-muted)", gap: 12 }
      }}
    >
      {modalTabs.length > 1 && !previewLoading && (
        <div className="mt-3 flex bg-[var(--app-surface)] p-1.5 rounded-xl border border-[var(--app-border)]/40 self-start shrink-0 select-none">
          <Segmented
            options={modalTabs}
            value={previewTab}
            onChange={(val) => setPreviewTab(val as 'original' | 'parsed')}
            size="small"
          />
        </div>
      )}

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
                <div className="w-full h-full overflow-auto extracted-html-container">
                  <div
                    className="markdown-content text-[var(--app-text)]"
                    dangerouslySetInnerHTML={{
                      __html: parsedText
                        ? (typeof marked === 'function' ? (marked as any)(parsedText) : (marked as any).parse(parsedText))
                        : "<p style='color: var(--app-text-muted)'>No extracted text content available.</p>"
                    }}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="w-full h-full flex flex-col justify-start overflow-hidden">
              {previewType === "image" && previewUrl ? (
                <div className="w-full h-full flex items-center justify-center p-4 bg-neutral-900/5 overflow-auto">
                  <img
                    src={previewUrl}
                    alt={previewItem?.name || "Preview"}
                    style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: "8px" }}
                  />
                </div>
              ) : (previewType === "excel" || previewType === "csv") && excelSheetNames.length > 0 ? (
                <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--app-surface)]">
                  {/* Excel Multi-sheet Switcher */}
                  {previewType === "excel" && excelSheetNames.length > 1 && (
                    <div className="flex gap-2 p-2.5 bg-[var(--app-surface-muted)] border-b border-[var(--app-border)]/40 overflow-x-auto shrink-0 scrollbar-thin">
                      {excelSheetNames.map(sheetName => {
                        const isActive = activeExcelSheet === sheetName;
                        return (
                          <button
                            key={sheetName}
                            onClick={() => setActiveExcelSheet(sheetName)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${isActive
                                ? "bg-[#285d91] text-white shadow-sm"
                                : "bg-[var(--app-surface)] hover:bg-[var(--app-surface-muted)] text-[var(--app-text-soft)] border border-[var(--app-border)]/40"
                              }`}
                          >
                            {sheetName}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {/* Spreadsheet Grid */}
                  <div className="flex-1 overflow-auto p-4 custom-scrollbar bg-[var(--app-surface)]">
                    {excelSheets[activeExcelSheet] && excelSheets[activeExcelSheet].length > 0 ? (
                      <div className="border border-[var(--app-border)]/40 rounded-xl overflow-hidden shadow-sm">
                        <table className="min-w-full divide-y divide-[var(--app-border)]/40 text-left text-xs bg-[var(--app-surface)]">
                          <thead className="bg-[var(--app-surface-muted)] font-bold text-[var(--app-text)] uppercase tracking-wider">
                            <tr>
                              {excelSheets[activeExcelSheet][0].map((cell, idx) => (
                                <th key={idx} className="px-4 py-3 border-b border-r border-[var(--app-border)]/40 last:border-r-0 whitespace-nowrap bg-[var(--app-surface-muted)] text-[var(--app-text)] font-extrabold text-[10px] tracking-wider">
                                  {cell || `Column ${idx + 1}`}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="bg-[var(--app-surface)] divide-y divide-[var(--app-border)]/40 text-[var(--app-text-soft)] font-medium">
                            {excelSheets[activeExcelSheet].slice(1).map((row, rowIdx) => (
                              <tr key={rowIdx} className="hover:bg-[var(--app-surface-muted)]/50 transition-colors">
                                {excelSheets[activeExcelSheet][0].map((_, colIdx) => (
                                  <td key={colIdx} className="px-4 py-3 border-r border-[var(--app-border)]/40 last:border-r-0 max-w-xs truncate whitespace-nowrap text-[var(--app-text-soft)]">
                                    {row[colIdx] || ""}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <Flex vertical align="center" justify="center" className="py-20 text-[var(--app-text-soft)] h-full">
                        <FileText size={32} className="mb-2 opacity-55" />
                        <span className="text-xs">No data in this sheet</span>
                      </Flex>
                    )}
                  </div>
                </div>
              ) : previewUrl ? (
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
