"use client";

import React from "react";
import { Table, Button, Input, Space, Badge, Typography, Card } from "antd";
import { EditOutlined, DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { User } from "../types";

const { Text } = Typography;

interface UserTableProps {
  users: User[];
  loading: boolean;
  total: number;
  skip: number;
  limit: number;
  onEdit: (user: User) => void;
  onDelete: (user: User) => void;
  onPaginationChange: (page: number, pageSize: number) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export default function UserTable({
  users,
  loading,
  total,
  skip,
  limit,
  onEdit,
  onDelete,
  onPaginationChange,
  searchQuery,
  onSearchChange,
}: UserTableProps) {
  const columns = [
    {
      title: "S.No",
      key: "sno",
      width: 80,
      render: (_: any, __: any, index: number) => {
        return <Text className="font-bold text-[var(--app-text-soft)]">{skip + index + 1}</Text>;
      },
    },
    {
      title: "Name",
      key: "name",
      render: (record: User) => {
        const fullName = `${record.first_name || ""} ${record.last_name || ""}`.trim();
        return (
          <Text className="font-semibold text-[var(--app-text)]">
            {fullName || "N/A"}
          </Text>
        );
      },
    },
    {
      title: "Email",
      dataIndex: "email",
      key: "email",
      render: (email: string) => <Text className="text-[var(--app-text-soft)]">{email}</Text>,
    },
    {
      title: "Username",
      dataIndex: "username",
      key: "username",
      render: (username: string) => <Text className="text-[var(--app-text-soft)]">{username}</Text>,
    },
    {
      title: "Status",
      dataIndex: "is_active",
      key: "is_active",
      width: 120,
      render: (isActive: boolean) => (
        <Badge
          status={isActive ? "success" : "default"}
          text={isActive ? "Active" : "Inactive"}
          className="font-semibold"
        />
      ),
    },
    {
      title: "Role",
      dataIndex: "role",
      key: "role",
      width: 120,
      render: (role: string) => (
        <span className="px-2 py-0.5 rounded-md text-[10px] font-black uppercase tracking-wider bg-[var(--app-active-bg)] text-[#0fb5a1]">
          {role || "user"}
        </span>
      ),
    },
    {
      title: "Created Date",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (dateStr: string) => (
        <Text className="text-[var(--app-text-soft)] font-medium text-xs">
          {dateStr ? dayjs(dateStr).format("DD MMM YYYY, hh:mm A") : "N/A"}
        </Text>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      width: 120,
      render: (record: User) => (
        <Space size="middle">
          <Button
            type="text"
            icon={<EditOutlined className="text-[#0fb5a1]" />}
            onClick={() => onEdit(record)}
            className="hover:bg-[#0fb5a1]/10 rounded-lg flex items-center justify-center p-2"
          />
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => onDelete(record)}
            className="hover:bg-red-500/10 rounded-lg flex items-center justify-center p-2"
          />
        </Space>
      ),
    },
  ];

  const paginationConfig = {
    current: Math.floor(skip / limit) + 1,
    pageSize: limit,
    total: total,
    showSizeChanger: true,
    pageSizeOptions: ["10", "20", "50", "100"],
    onChange: onPaginationChange,
  };

  return (
    <Card className="bg-[var(--app-surface)] border-[var(--app-border)] shadow-sm rounded-2xl p-4 overflow-hidden">
      <Space direction="vertical" size={16} className="w-full">
        <div style={{ maxWidth: 360 }}>
          <Input
            placeholder="Search users..."
            prefix={<SearchOutlined className="text-[var(--app-text-soft)] mr-1" />}
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="h-11 !rounded-xl !bg-[var(--app-surface-muted)] !border-none font-bold text-[var(--app-text)]"
          />
        </div>

        <Table
          columns={columns}
          dataSource={users}
          rowKey="id"
          loading={loading}
          pagination={paginationConfig}
          className="custom-table"
        />
      </Space>
    </Card>
  );
}
