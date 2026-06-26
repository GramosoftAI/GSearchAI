"use client";

import React from 'react';
import { Button, Typography, Space, Row, Col, Card} from 'antd';
import { 
  Database, 
  Cpu, 
  Network, 
  BarChart3, 
  MessageSquare, 
  Globe, 
  ShieldCheck, 
  Zap,
  ArrowRight,
  // ChevronRight
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { routes } from '@/app/services/routes';

const { Title, Text } = Typography;

const FeatureCard = ({ icon: Icon, title, description }: { icon: any, title: string, description: string }) => (
  <Card
    className="feature-card"
    style={{
      background: 'rgba(255, 255, 255, 0.8)',
      border: '1px solid rgba(226, 232, 240, 0.8)',
      borderRadius: '32px',
      height: '100%',
      transition: 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
      backdropFilter: 'blur(10px)',
    }}
    styles={{ body: { padding: '32px' } }}
  >
    <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#2879f3]/5 text-[#2879f3] shadow-inner">
      <Icon size={28} />
    </div>
    <Title level={4} style={{ color: '#0f172a', marginBottom: '16px', fontWeight: 800, letterSpacing: '-0.01em' }}>{title}</Title>
    <Text style={{ color: '#64748b', fontSize: '16px', lineHeight: '1.6', fontWeight: 500 }}>{description}</Text>
  </Card>
);

const LandingPage = () => {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-[#f8fafc] text-[#0f172a] font-sans selection:bg-[#2879f3]/10 selection:text-[#2879f3]">
      {/* Decorative Circles (Matching Auth Pages) */}
      <div className="fixed top-[-100px] left-[-100px] h-[500px] w-[500px] rounded-full bg-[#2879f3]/5 blur-[120px] pointer-events-none" />
      <div className="fixed bottom-[-100px] right-[-100px] h-[500px] w-[500px] rounded-full bg-[#f37e10]/5 blur-[120px] pointer-events-none" />

      {/* Navbar */}
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white/70 backdrop-blur-xl border-b border-slate-200/50">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-3 cursor-pointer group" onClick={() => router.push("/")}>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#2879f3] shadow-lg shadow-blue-500/20 transition-transform group-hover:scale-110">
              <span className="text-sm font-black text-white">GS</span>
            </div>
            <span className="text-2xl font-black tracking-tighter text-[#0f172a]">Gsearch AI</span>
          </div>

          {/* <div className="hidden md:flex items-center gap-10">
            {['Features', 'Intelligence', 'Security'].map((item) => (
              <a key={item} href="#" className="text-sm font-bold text-slate-500 hover:text-[#2879f3] transition-colors">
                {item}
              </a>
            ))}
          </div> */}

          <div className="flex items-center gap-4">
            <Button 
              type="text" 
              onClick={() => router.push(routes.login)}
              className="!text-slate-600 !font-bold !text-sm hover:!text-[#2879f3]"
            >
              Log In
            </Button>
            <Button 
              onClick={() => router.push(routes.register)}
              className="!h-11 !px-6 !rounded-xl !bg-[#2879f3] !border-none !text-white !font-bold !text-sm hover:!scale-105 transition-all shadow-lg shadow-blue-500/20"
            >
              Start Building
            </Button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 flex flex-col items-center justify-center px-6 pt-48 pb-32 text-center overflow-hidden">
        <div className="mb-8 flex items-center gap-2 rounded-full border border-[#2879f3]/10 bg-[#2879f3]/5 px-5 py-2 text-sm font-bold text-[#2879f3] animate-in slide-in-from-top-4 duration-1000">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#2879f3] opacity-75"></span>
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#2879f3]"></span>
          </span>
          Next-Gen Graph RAG Intelligence
        </div>

        <Title 
          className="mx-auto max-w-5xl !text-[#0f172a]"
          style={{ 
            fontSize: 'clamp(2.5rem, 8vw, 5rem)', 
            fontWeight: 900, 
            lineHeight: 1.05,
            letterSpacing: '-0.04em',
            marginBottom: '32px'
          }}
        >
          Build AI Agents powered by <br/>
          your <span className="text-[#2879f3] relative">
            knowledge graph
            <svg className="absolute -bottom-2 left-0 w-full h-3 text-[#2879f3]/20" viewBox="0 0 100 10" preserveAspectRatio="none">
              <path d="M0 5 Q 25 0, 50 5 T 100 5" fill="none" stroke="currentColor" strokeWidth="4" />
            </svg>
          </span>
        </Title>

        <Text className="mx-auto mb-12 max-w-2xl block text-slate-500 font-medium" style={{ fontSize: '1.25rem', lineHeight: '1.6' }}>
          Gsearch transforms complex relationships into actionable intelligence. 
          Deploy context-aware agents that reason like humans.
        </Text>

        <Space size={20} className="mb-24">
          <Button 
            size="large" 
            onClick={() => router.push(routes.register)}
            className="!h-16 !px-10 !rounded-2xl !bg-[#2879f3] !border-none !text-white !font-black !text-lg hover:!scale-105 transition-all shadow-2xl shadow-blue-500/30 flex items-center gap-2"
          >
            Create Your Bot <ArrowRight size={20} />
          </Button>
          <Button 
            size="large" 
            className="!h-16 !px-10 !rounded-2xl !bg-white !border-2 !border-slate-200 !text-slate-700 !font-black !text-lg hover:!border-[#2879f3] hover:!text-[#2879f3] transition-all"
          >
            Watch Demo
          </Button>
        </Space>

        {/* Floating Mockup (Glassmorphic) */}
        <div className="relative mx-auto max-w-5xl w-full perspective-1000">
          <div className="rounded-[40px] border border-white bg-white/40 p-4 shadow-[0_32px_64px_-16px_rgba(0,0,0,0.1)] backdrop-blur-2xl animate-in fade-in zoom-in duration-1000 delay-300">
            <div className="rounded-[32px] overflow-hidden border border-slate-200 bg-white shadow-sm">
              <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-slate-50/50">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1.5">
                    <div className="h-3 w-3 rounded-full bg-slate-200"></div>
                    <div className="h-3 w-3 rounded-full bg-slate-200"></div>
                    <div className="h-3 w-3 rounded-full bg-slate-200"></div>
                  </div>
                  <span className="ml-4 text-xs text-slate-400 font-bold uppercase tracking-widest">Gsearch Workspace</span>
                </div>
                <div className="h-6 w-32 rounded-full bg-slate-200/50"></div>
              </div>
              <div className="p-8 text-left bg-white">
                <div className="mb-8 flex justify-end">
                  <div className="max-w-[70%] rounded-3xl bg-[#f1f5f9] px-6 py-4 text-[15px] font-semibold text-slate-700 shadow-sm">
                    Analyze the correlation between user churn and knowledge base coverage.
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[85%] rounded-3xl border border-[#2879f3]/10 bg-white px-6 py-6 text-[15px] text-slate-600 shadow-[0_10px_30px_rgba(40,121,243,0.05)]">
                    <p className="mb-4 font-semibold text-slate-800">Ive traversed your knowledge graph and identified a critical pattern:</p>
                    <div className="space-y-3">
                      <div className="flex items-center gap-3 p-3 rounded-2xl bg-[#2879f3]/5 border border-[#2879f3]/10">
                        <div className="h-8 w-8 rounded-lg bg-[#2879f3] text-white flex items-center justify-center">
                          <Network size={16} />
                        </div>
                        <span className="font-bold text-sm text-[#2879f3]">High Correlation Found (0.87)</span>
                      </div>
                      <p className="pl-2 border-l-2 border-slate-100">Users who encounter Empty Graph Node errors in the Billing entity have a 40% higher churn rate within 7 days.</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="relative z-10 px-6 py-40 mx-auto max-w-7xl">
        <div className="text-center mb-20">
          <Title 
            level={2} 
            className="!text-[#0f172a]" 
            style={{ fontSize: '3.5rem', fontWeight: 900, letterSpacing: '-0.03em' }}
          >
            Engineering <span className="text-[#2879f3]">Cognitive Intelligence</span>
          </Title>
          <Text className="text-slate-500 font-bold text-lg">Every module built for enterprise-scale graph reasoning.</Text>
        </div>

        <Row gutter={[32, 32]}>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={Database} 
              title="Knowledge Base" 
              description="Unified ingestion for URLs, PDFs, and unstructured text into vector-graph indices." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={Cpu} 
              title="AI Agents" 
              description="Orchestrate multi-agent workflows with deterministic routing and role-specific memory." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={Network} 
              title="Graph RAG" 
              description="Neo4j-powered retrieval that understands entity relationships and multi-hop logic." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={BarChart3} 
              title="Intelligence" 
              description="Deep analytics on query accuracy, confidence thresholds, and knowledge gaps." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={MessageSquare} 
              title="Playground" 
              description="Real-time debugging of reasoning paths, retrieved triplets, and graph traversals." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={Zap} 
              title="Deployment" 
              description="Production-ready SDKs, customizable widgets, and high-throughput REST APIs." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={ShieldCheck} 
              title="Compliance" 
              description="SOC2 compliant security with granular RLS and comprehensive audit logging." 
            />
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <FeatureCard 
              icon={Globe} 
              title="Localization" 
              description="Native support for 50+ languages with automatic cross-lingual reasoning." 
            />
          </Col>
        </Row>
      </section>

      {/* CTA Section */}
      <section className="px-6 py-32">
        <div className="mx-auto max-w-5xl rounded-[48px] bg-gradient-to-br from-[#2879f3] to-[#1d64d1] p-16 text-center text-white relative overflow-hidden shadow-2xl shadow-blue-500/20">
          <div className="absolute top-0 right-0 h-64 w-64 bg-white/10 blur-3xl rounded-full translate-x-1/2 -translate-y-1/2" />
          <div className="absolute bottom-0 left-0 h-64 w-64 bg-black/10 blur-3xl rounded-full -translate-x-1/2 translate-y-1/2" />
          
          <Title level={2} className="!text-white !mb-6" style={{ fontSize: '3rem', fontWeight: 900, letterSpacing: '-0.02em' }}>
            Ready to unleash your graph?
          </Title>
          <Text className="text-white/80 block mb-10 text-lg font-semibold">Join 500+ enterprises building the future of AI on Gsearch.</Text>
          <Button 
            size="large" 
            onClick={() => router.push(routes.register)}
            className="!h-16 !px-12 !rounded-2xl !bg-white !border-none !text-[#2879f3] !font-black !text-xl hover:!scale-105 transition-all shadow-xl"
          >
            Create Your Free Account
          </Button>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-200 py-20 bg-white">
        <div className="mx-auto max-w-7xl px-6 text-center">
          <div className="flex items-center justify-center gap-2 mb-8">
            <div className="h-6 w-6 rounded bg-[#2879f3] flex items-center justify-center text-[8px] font-black text-white">GS</div>
            <span className="text-lg font-black tracking-tight">Gsearch AI</span>
          </div>
          <Text style={{ color: '#94a3b8', fontSize: '15px', fontWeight: 600 }}>
            © 2026 Gsearch AI Systems. All rights reserved. Built for the era of Knowledge Graphs.
          </Text>
        </div>
      </footer>

      <style jsx global>{`
        .feature-card:hover {
          transform: translateY(-12px) scale(1.02);
          border-color: #2879f3 !important;
          box-shadow: 0 30px 60px -12px rgba(40, 121, 243, 0.15) !important;
        }
        .perspective-1000 { perspective: 1000px; }
      `}</style>
    </div>
  );
};

export default LandingPage;
