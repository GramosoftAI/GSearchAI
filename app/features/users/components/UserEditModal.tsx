"use client";

import React, { useEffect } from "react";
import { Modal, Form, Input, Switch, Select, Button, Typography, Row, Col, Divider } from "antd";
import { UserOutlined, MailOutlined, SettingOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { User, UpdateUserPayload } from "../types";

const { Text, Title } = Typography;

interface UserEditModalProps {
  open: boolean;
  onCancel: () => void;
  onSubmit: (values: UpdateUserPayload) => void;
  user: User | null;
  loading: boolean;
}

export default function UserEditModal({
  open,
  onCancel,
  onSubmit,
  user,
  loading,
}: UserEditModalProps) {
  const [form] = Form.useForm();

  // Populate form fields when active user changes
  useEffect(() => {
    if (open && user) {
      form.setFieldsValue({
        first_name: user.first_name,
        last_name: user.last_name,
        email: user.email,
        username: user.username,
        role: user.role || "user",
        is_active: user.is_active,
      });
    } else {
      form.resetFields();
    }
  }, [open, user, form]);

  const handleFinish = (values: any) => {
    onSubmit(values);
  };

  return (
    <Modal
      title={
        <div className="py-2 border-b border-[var(--app-border)]/40 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#0fb5a1]/10 text-[#0fb5a1] flex items-center justify-center text-lg">
            <UserOutlined />
          </div>
          <div>
            <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
              Edit User Settings
            </Title>
            <Text className="text-[var(--app-text-soft)] text-xs font-semibold uppercase tracking-wider block mt-0.5">
              Modify account attributes and access roles.
            </Text>
          </div>
        </div>
      }
      open={open}
      onCancel={onCancel}
      footer={null}
      centered
      width={600}
      styles={{ body: { padding: "16px 24px" } }}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        className="mt-6"
      >
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              name="first_name"
              label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">First Name</Text>}
              rules={[{ required: true, message: "Please enter first name" }]}
            >
              <Input
                placeholder="e.g. John"
                className="h-11 !rounded-xl !bg-[var(--app-surface-muted)] !border-none font-semibold text-[var(--app-text)]"
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="last_name"
              label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Last Name</Text>}
              rules={[{ required: true, message: "Please enter last name" }]}
            >
              <Input
                placeholder="e.g. Doe"
                className="h-11 !rounded-xl !bg-[var(--app-surface-muted)] !border-none font-semibold text-[var(--app-text)]"
              />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="email"
          label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Email Address</Text>}
          rules={[
            { required: true, message: "Please enter email address" },
            { type: "email", message: "Please enter a valid email address" },
          ]}
        >
          <Input
            prefix={<MailOutlined className="text-slate-400 mr-1" />}
            placeholder="user@example.com"
            className="h-11 !rounded-xl !bg-[var(--app-surface-muted)] !border-none font-semibold text-[var(--app-text)]"
          />
        </Form.Item>

        <Form.Item
          name="username"
          label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Username</Text>}
          rules={[{ required: true, message: "Please enter username" }]}
        >
          <Input
            prefix={<UserOutlined className="text-slate-400 mr-1" />}
            placeholder="username"
            className="h-11 !rounded-xl !bg-[var(--app-surface-muted)] !border-none font-semibold text-[var(--app-text)]"
          />
        </Form.Item>

        <Row gutter={16} align="middle">
          <Col span={12}>
            <Form.Item
              name="role"
              label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Access Role</Text>}
              rules={[{ required: true, message: "Please select access role" }]}
            >
              <Select
                placeholder="Select access role"
                className="h-11 custom-select"
                options={[
                  { label: "Admin", value: "admin" },
                  { label: "User", value: "user" },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="is_active"
              label={<Text className="font-black text-[10px] uppercase tracking-widest text-[var(--app-text-soft)]">Account Status</Text>}
              valuePropName="checked"
            >
              <Switch checkedChildren="Active" unCheckedChildren="Inactive" />
            </Form.Item>
          </Col>
        </Row>

        {user && (
          <>
            <Divider className="my-4 border-[var(--app-border)]/40" />
            <Row gutter={16} className="bg-[var(--app-surface-muted)]/50 p-3.5 rounded-xl border border-[var(--app-border)]/40 mb-6">
              <Col span={12}>
                <Text className="text-[10px] font-black uppercase tracking-widest text-[var(--app-text-soft)] block">Created At</Text>
                <Text className="text-xs font-bold text-[var(--app-text)] mt-1 block">
                  {user.created_at ? dayjs(user.created_at).format("DD MMM YYYY, hh:mm A") : "N/A"}
                </Text>
              </Col>
              <Col span={12}>
                <Text className="text-[10px] font-black uppercase tracking-widest text-[var(--app-text-soft)] block">Last Updated</Text>
                <Text className="text-xs font-bold text-[var(--app-text)] mt-1 block">
                  {user.updated_at ? dayjs(user.updated_at).format("DD MMM YYYY, hh:mm A") : "N/A"}
                </Text>
              </Col>
            </Row>
          </>
        )}

        <Button
          type="primary"
          htmlType="submit"
          loading={loading}
          icon={<SettingOutlined />}
          className="w-full h-14 !rounded-xl !bg-[#0fb5a1] !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-lg mt-2 hover:!scale-[1.01] active:!scale-100 transition-all"
        >
          Save Changes
        </Button>
      </Form>
    </Modal>
  );
}
