"use client"
import { Flex, Typography, Button, Spin } from 'antd'
import { useRouter, useParams } from 'next/navigation'
import { useEffect } from 'react'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { FaRobot } from 'react-icons/fa6'
import useAxios from '../../../hooks/useAxios'

const { Title, Text } = Typography

export default function AgentDetailPage() {
    const router = useRouter()
    const params = useParams()
    const id = params?.id as string

    const [getAgent, res] = useAxios<any>({ endpoint: "GETAGENTLIST" })

    useEffect(() => {
        if (id) getAgent({ path: `/${id}` })
    }, [id])

    const agent = res?.data?.agent

    return (
        <Flex vertical gap={24} style={{ maxWidth: '75%', marginBottom: 40 }}>

            {/* Header */}
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
                    {/* Icon + Status */}
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

                    {/* Description */}
                    <div>
                        <Text strong style={{ color: '#fff', display: 'block', marginBottom: 4 }}>Description</Text>
                        <Text style={{ color: '#9ca3af' }}>{agent.description ?? "No description"}</Text>
                    </div>

                    {/* System Prompt */}
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

                    {/* Personality */}
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

                    {/* Capabilities */}
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
                </Flex>
            )}
        </Flex>
    )
}