"use client"
import { Flex, Typography, Button, Spin, Tag } from 'antd'
import { useRouter, useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { ArrowLeftOutlined, DatabaseOutlined, FileTextOutlined } from '@ant-design/icons'
import { FaRobot } from 'react-icons/fa6'
import useAxios from '../../../hooks/useAxios'
import { API_BASE_URL, AUTH_COOKIE_KEY } from '../../../config/config'
import { getCookie } from '../../../config/cookies'

const { Title, Text } = Typography

interface AttachedDocSource {
    id: string;
    name: string;
    source_type?: string;
    file_type?: string;
    status?: string;
}

interface AttachedDbKb {
    id: string;
    name: string;
    database_type: string;
    status: string;
    schema_version?: string;
}

export default function AgentDetailPage() {
    const router = useRouter()
    const params = useParams()
    const id = ((params?.botId || params?.id) as string) || ""

    const [getAgent, res] = useAxios<any>({ endpoint: "GETAGENTLIST" })
    const [docSources, setDocSources] = useState<AttachedDocSource[]>([])
    const [dbKbs, setDbKbs] = useState<AttachedDbKb[]>([])
    const [sourcesLoading, setSourcesLoading] = useState(false)

    useEffect(() => {
        if (!id) return
        getAgent({ path: `/${id}` })

        const token = getCookie(AUTH_COOKIE_KEY)
        const headers = {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
        }
        setSourcesLoading(true)
        Promise.all([
            fetch(`${API_BASE_URL}/knowledge-bases/agents/${id}?limit=100&offset=0`, { headers })
                .then((r) => (r.ok ? r.json() : null))
                .catch(() => null),
            fetch(`${API_BASE_URL}/database-knowledgebases?agent_id=${id}`, { headers })
                .then((r) => (r.ok ? r.json() : null))
                .catch(() => null),
        ])
            .then(([docJson, dbJson]) => {
                const rawDoc = docJson?.data ?? docJson
                const docs = Array.isArray(rawDoc)
                    ? rawDoc
                    : Array.isArray(rawDoc?.sources)
                        ? rawDoc.sources
                        : Array.isArray(rawDoc?.kbs)
                            ? rawDoc.kbs
                            : []
                setDocSources(docs)
                setDbKbs(Array.isArray(dbJson?.data) ? dbJson.data : [])
            })
            .finally(() => setSourcesLoading(false))
    }, [id])

    const agent = res?.data?.agent

    return (
        <Flex vertical gap={24} style={{ maxWidth: '75%', marginBottom: 40 }}>

           
            <Flex gap={8} align="center">
                <Button
                    type="text"
                    icon={<ArrowLeftOutlined style={{ color: '#9ca3af' }} />}
                    onClick={() => router.back()}
                    style={{ background: 'transparent', border: 'none', padding: '6px 8px', borderRadius: 6 }}
                />
                <div>
                    <Title level={3} style={{ color: '#fff', margin: 0, fontWeight: 700 }}>
                        {agent?.name ?? 'Agent Detail'}
                    </Title>
                    <Text style={{ color: '#6b7280', fontSize: 13 }}>View and manage this agent</Text>
                </div>
            </Flex>

            <div style={{ borderBottom: '1px solid #374151' }} />

            {!agent ? (
                <Flex justify="center" style={{ padding: 40 }}>
                    <Spin size="large" />
                </Flex>
            ) : (
                <Flex vertical gap={20}>
                    
                    <Flex align="center" gap={16}>
                        <Flex
                            align="center"
                            justify="center"
                            style={{ width: 52, height: 52, background: '#052e16', borderRadius: 12 }}
                        >
                            <FaRobot style={{ color: '#4ade80', fontSize: 24 }} />
                        </Flex>
                        <div>
                            <Title level={4} style={{ color: '#fff', margin: 0 }}>{agent.name}</Title>
                            <span style={{
                                fontSize: 12,
                                background: '#2d2d2d',
                                color: '#9ca3af',
                                padding: '2px 12px',
                                borderRadius: 9999,
                                display: 'inline-block',
                                marginTop: 4,
                            }}>
                                {agent.is_active ? "active" : "draft"}
                            </span>
                        </div>
                    </Flex>

                   
                    <div>
                        <Text strong style={{ color: '#fff', display: 'block', marginBottom: 4 }}>Description</Text>
                        <Text style={{ color: '#9ca3af' }}>{agent.description ?? "No description"}</Text>
                    </div>

                    
                    <div>
                        <Text strong style={{ color: '#fff', display: 'block', marginBottom: 4 }}>System Prompt</Text>
                        <div style={{
                            background: 'transparent',
                            border: '1px solid #2d2d2d',
                            borderRadius: 8,
                            padding: '10px 14px',
                            color: '#ccc',
                            fontSize: 13,
                            lineHeight: 1.6,
                        }}>
                            {agent.system_prompt}
                        </div>
                    </div>

                    
                    <div>
                        <Text strong style={{ color: '#fff', display: 'block', marginBottom: 8 }}>Personality</Text>
                        <span style={{
                            background: '#22c55e',
                            color: '#000',
                            padding: '6px 16px',
                            borderRadius: 8,
                            fontWeight: 600,
                            fontSize: 14,
                        }}>
                            {agent.personality}
                        </span>
                    </div>

                    
                    <div>
                        <Text strong style={{ color: '#fff', display: 'block', marginBottom: 8 }}>Capabilities</Text>
                        <Flex vertical gap={8}>
                            <Flex justify="space-between" align="center" style={{
                                background: '#111',
                                border: '1px solid #2d2d2d',
                                borderRadius: 8,
                                padding: '10px 14px',
                            }}>
                                <div>
                                    <Text strong style={{ color: '#fff', fontSize: 13 }}>Memory</Text>
                                    <Text style={{ color: '#6b7280', fontSize: 12, display: 'block' }}>Remember conversation context</Text>
                                </div>
                                <span style={{
                                    width: 10, height: 10, borderRadius: '50%',
                                    background: agent.memory ? '#22c55e' : '#4b5563',
                                    display: 'inline-block',
                                }} />
                            </Flex>
                            <Flex justify="space-between" align="center" style={{
                                background: '#111',
                                border: '1px solid #2d2d2d',
                                borderRadius: 8,
                                padding: '10px 14px',
                            }}>
                                <div>
                                    <Text strong style={{ color: '#fff', fontSize: 13 }}>Reasoning</Text>
                                    <Text style={{ color: '#6b7280', fontSize: 12, display: 'block' }}>Show reasoning path in responses</Text>
                                </div>
                                <span style={{
                                    width: 10, height: 10, borderRadius: '50%',
                                    background: agent.reasoning ? '#22c55e' : '#4b5563',
                                    display: 'inline-block',
                                }} />
                            </Flex>
                        </Flex>
                    </div>

                    <div>
                        <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
                            <Text strong style={{ color: '#fff', display: 'block' }}>Attached Knowledge Sources</Text>
                            <Flex gap={8}>
                                <Tag color={docSources.length > 0 && dbKbs.length > 0 ? "cyan" : dbKbs.length > 0 ? "teal" : "blue"}>
                                    {docSources.length > 0 && dbKbs.length > 0
                                        ? "Hybrid (Docs + Live DB)"
                                        : dbKbs.length > 0
                                            ? "Structured DB Only"
                                            : "Documents / URLs"}
                                </Tag>
                                <Button size="small" onClick={() => router.push('/dashboard/database-knowledge')}>
                                    Manage DB Connections
                                </Button>
                            </Flex>
                        </Flex>
                        {sourcesLoading ? (
                            <Spin size="small" />
                        ) : (
                            <Flex vertical gap={8}>
                                {dbKbs.map((dbk) => (
                                    <Flex key={dbk.id} justify="space-between" align="center" style={{
                                        background: '#082f2c',
                                        border: '1px solid #0f766e',
                                        borderRadius: 8,
                                        padding: '10px 14px',
                                    }}>
                                        <Flex align="center" gap={10}>
                                            <DatabaseOutlined style={{ color: '#2dd4bf', fontSize: 16 }} />
                                            <div>
                                                <Text strong style={{ color: '#fff', fontSize: 13 }}>{dbk.name}</Text>
                                                <Text style={{ color: '#99f6e4', fontSize: 11, display: 'block' }}>
                                                    Live DB • {dbk.database_type.toUpperCase()} • {dbk.status}
                                                </Text>
                                            </div>
                                        </Flex>
                                        <Tag color="green">LIVE STRUCTURED KB</Tag>
                                    </Flex>
                                ))}
                                {docSources.map((doc) => (
                                    <Flex key={doc.id} justify="space-between" align="center" style={{
                                        background: '#111',
                                        border: '1px solid #2d2d2d',
                                        borderRadius: 8,
                                        padding: '10px 14px',
                                    }}>
                                        <Flex align="center" gap={10}>
                                            <FileTextOutlined style={{ color: '#60a5fa', fontSize: 15 }} />
                                            <div>
                                                <Text strong style={{ color: '#fff', fontSize: 13 }}>{doc.name}</Text>
                                                <Text style={{ color: '#6b7280', fontSize: 11, display: 'block' }}>
                                                    {(doc.source_type || doc.file_type || 'DOCUMENT').toUpperCase()} • {doc.status || 'indexed'}
                                                </Text>
                                            </div>
                                        </Flex>
                                        <Tag color="blue">DOCUMENT KB</Tag>
                                    </Flex>
                                ))}
                                {dbKbs.length === 0 && docSources.length === 0 && (
                                    <Text style={{ color: '#6b7280', fontSize: 12 }}>
                                        No document or database knowledge sources are attached to this agent yet.
                                    </Text>
                                )}
                            </Flex>
                        )}
                    </div>
                </Flex>
            )}
        </Flex>
    )
}