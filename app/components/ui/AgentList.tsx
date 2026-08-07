"use client"
import { Select } from 'antd'
import { useAgents } from '../../hooks/useAgents'
import styles from './AgentList.module.css'

interface AgentListProps {
  selectedId?: string
  onChange: (id: string, name: string) => void
  style?: React.CSSProperties
  size?: "small" | "middle" | "large"
  className?: string
}

export default function AgentList({ selectedId, onChange, style, size = "middle", className }: AgentListProps) {
  const { agents: agentList } = useAgents();

  function handleChange(value: string) {
    const found = agentList?.find((agent) => agent.id === value)
    if (found) onChange(found.id, found.name)
  }

  const defaultStyle = { width: 160, ...style };

  return (
    <div className={`${styles.dropdownWrapper} ${className || ""}`} style={defaultStyle}>
      <Select
        showSearch
        optionFilterProp="label"
        size={size}
        value={selectedId ?? undefined}
        onChange={handleChange}
        placeholder="Select agent"
        style={{ width: '100%', height: '100%' }}
        getPopupContainer={(triggerNode) => triggerNode.parentNode}
        classNames={{
          popup: { root: styles.dropdown },
        }}
        options={agentList?.map((agent) => ({
          value: agent.id,
          label: agent.name,
        }))}
      />
    </div>
  )
}
