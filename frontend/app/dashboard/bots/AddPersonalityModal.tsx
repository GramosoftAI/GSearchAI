"use client"
import { Modal, Input, Typography } from 'antd'
import { useState, useEffect } from 'react'
import { PlusOutlined } from '@ant-design/icons'

const { Text } = Typography

interface AddPersonalityModalProps {
    open: boolean
    existingPersonalities: string[]
    onAdd: (personality: string) => void
    onCancel: () => void
}

export default function AddPersonalityModal({
    open,
    existingPersonalities,
    onAdd,
    onCancel,
}: AddPersonalityModalProps) {
    const [value, setValue] = useState('')

    useEffect(() => {
        if (open) setValue('')
    }, [open])

    const isDuplicate = existingPersonalities
        .map((p) => p.toLowerCase())
        .includes(value.trim().toLowerCase())

    const isValid = value.trim().length > 0 && !isDuplicate

    function handleSave() {
        if (!isValid) return
        onAdd(value.trim())
        setValue('')
    }

    function handleCancel() {
        setValue('')
        onCancel()
    }

    return (
        <Modal
            title={
                <>
                    <PlusOutlined /> Add Custom Personality
                </>
            }
            centered
            open={open}
            onOk={handleSave}
            onCancel={handleCancel}
            okText="Add"
            cancelText="Back"
            okButtonProps={{ disabled: !isValid }}
        >
            <div>
                <Text>Personality Name</Text>
                <Input
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    onPressEnter={handleSave}
                    placeholder="e.g. Empathetic, Witty, Concise..."
                    maxLength={20}
                    showCount
                    status={isDuplicate ? 'error' : undefined}
                />

                {isDuplicate && (
                    <Text type="danger">
                        This personality already exists.
                    </Text>
                )}

                <Text type="secondary">
                    This will be added to your personality options.
                </Text>
            </div>
        </Modal>
    )
}