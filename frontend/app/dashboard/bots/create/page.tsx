"use client"
import useAxios from '../../../hooks/useAxios'
import { Flex, Form, Input, Switch, Button, Typography } from 'antd'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'
import AddPersonalityModal from '../AddPersonalityModal' // adjust path as needed

const { Title, Text } = Typography
const { TextArea } = Input

const DEFAULT_PERSONALITIES: string[] = [
    "Friendly", "Formal", "Sales", "Technical", "Sarcastic", "Arrogant"
]

export default function CreateBotPage() {
    const [createAgent] = useAxios({
        endpoint: "CREATEAGENT",
        successCb() {
            router.back()
        },
    })
    const router = useRouter()

    const [name, setName] = useState('')
    const [personalities, setPersonalities] = useState<string[]>(DEFAULT_PERSONALITIES)
    const [activePersonality, setActivePersonality] = useState<string>('Friendly')
    const [memory, setMemory] = useState(true)
    const [reasoning, setReasoning] = useState(true)
    const [systemPrompt, setSystemPrompt] = useState(
        'You are a helpful assistant that answers questions based on the provided knowledge base.'
    )

    // Modal visibility
    const [modalOpen, setModalOpen] = useState(false)

    // Called by modal when user clicks "Add"
    function handlePersonalityAdd(newPersonality: string) {
        setPersonalities((prev) => [...prev, newPersonality])
        setActivePersonality(newPersonality) // auto-select the new one
        setModalOpen(false)
    }

    const handleSave = () => {
        const payload = {
            name,
            personality: activePersonality,
            system_prompt: systemPrompt,
            memory,
            reasoning,
        }
        createAgent({ data: payload })
        console.log(payload)
    }

    const divider = <div style={{ borderBottom: '1px solid #374151', margin: '4px 0' }} />

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
                    <Title level={3} style={{ color: '#fff', margin: 0, fontWeight: 700 }}>Create Bot</Title>
                    <Text style={{ color: '#6b7280', fontSize: 13 }}>Configure your AI agent</Text>
                </div>
            </Flex>

            {divider}

            {/* Bot Name */}
            <Form.Item label={<Text strong style={{ color: '#fff' }}>Bot Name</Text>} style={{ marginBottom: 0 }}>
                <Input
                    value={name}
                    placeholder="e.g. Support Agent"
                    onChange={(e) => setName(e.target.value)}
                    style={{
                        background: 'transparent',
                        border: '1px solid #2d2d2d',
                        color: '#fff',
                        borderRadius: 8,
                    }}
                />
            </Form.Item>

            {/* Personality */}
            <div>
                <Text strong style={{ color: '#fff', display: 'block', marginBottom: 8 }}>Personality</Text>
                <Flex gap={12} wrap="wrap">
                    {personalities.map((p) => (
                        <button
                            key={p}
                            onClick={() => setActivePersonality(p)}
                            style={{
                                background: activePersonality === p ? '#22c55e' : 'transparent',
                                color: activePersonality === p ? '#000' : '#9ca3af',
                                border: `1px solid ${activePersonality === p ? '#22c55e' : '#374151'}`,
                                padding: '6px 16px',
                                borderRadius: 8,
                                fontWeight: activePersonality === p ? 600 : 400,
                                cursor: 'pointer',
                                fontSize: 14,
                                transition: 'all 0.15s',
                            }}
                        >
                            {p}
                        </button>
                    ))}

                    {/* Opens AddPersonalityModal */}
                    <button
                        onClick={() => setModalOpen(true)}
                        style={{
                            background: 'transparent',
                            color: '#9ca3af',
                            border: '1px dashed #374151',
                            padding: '6px 16px',
                            borderRadius: 8,
                            cursor: 'pointer',
                            fontSize: 14,
                            transition: 'all 0.15s',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 6,
                        }}
                    >
                        <PlusOutlined style={{ fontSize: 12 }} />
                        Custom
                    </button>
                </Flex>
            </div>

            {/* AddPersonalityModal — receives state and callbacks from this page */}
            <AddPersonalityModal
                open={modalOpen}
                existingPersonalities={personalities}
                onAdd={handlePersonalityAdd}
                onCancel={() => setModalOpen(false)}
            />

            {/* System Prompt */}
            <div>
                <Text strong style={{ color: '#fff', display: 'block', marginBottom: 8 }}>System Prompt</Text>
                <TextArea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    rows={5}
                    style={{
                        background: 'transparent',
                        border: '1px solid #2d2d2d',
                        color: '#ccc',
                        borderRadius: 8,
                        fontSize: 14,
                        resize: 'vertical',
                    }}
                />
            </div>

            {divider}

            {/* Capabilities */}
            <div>
                <Title level={4} style={{ color: '#fff', marginBottom: 16, fontWeight: 700 }}>Capabilities</Title>
                <Flex vertical gap={16}>
                    <Flex justify="space-between" align="center">
                        <div>
                            <Text strong style={{ color: '#fff', fontSize: 13, display: 'block' }}>Memory</Text>
                            <Text style={{ color: '#6b7280', fontSize: 12 }}>Remember conversation context</Text>
                        </div>
                        <Switch
                            checked={memory}
                            onChange={(checked) => setMemory(checked)}
                            style={{ background: memory ? '#22c55e' : '#374151' }}
                        />
                    </Flex>

                    <div style={{ borderBottom: '1px solid #1f2937' }} />

                    <Flex justify="space-between" align="center">
                        <div>
                            <Text strong style={{ color: '#fff', fontSize: 13, display: 'block' }}>Reasoning</Text>
                            <Text style={{ color: '#6b7280', fontSize: 12 }}>Show reasoning path in responses</Text>
                        </div>
                        <Switch
                            checked={reasoning}
                            onChange={(checked) => setReasoning(checked)}
                            style={{ background: reasoning ? '#22c55e' : '#374151' }}
                        />
                    </Flex>
                </Flex>
            </div>

            {divider}

            {/* Actions */}
            <Flex justify="flex-end" gap={12}>
                <Button
                    onClick={() => router.back()}
                    style={{ border: '1px solid #374151', color: '#9ca3af', background: 'transparent', borderRadius: 8 }}
                >
                    Cancel
                </Button>
                <Button
                    onClick={handleSave}
                    style={{ background: '#22c55e', color: '#000', fontWeight: 700, borderRadius: 8, border: 'none' }}
                >
                    Create Bot
                </Button>
            </Flex>

        </Flex>
    )
}