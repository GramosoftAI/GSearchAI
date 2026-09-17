"use client";

import { useEffect, useState, useMemo } from "react";
import { Typography, Button, Badge, Modal, Flex, Row, Col } from "antd";
import { ReloadOutlined, InfoCircleOutlined } from "@ant-design/icons";

import UserTable from "@/app/features/users/components/UserTable";
import UserEditModal from "@/app/features/users/components/UserEditModal";
import {
  useGetUsersApi,
  useUpdateUserApi,
  useDeleteUserApi,
} from "@/app/features/users/api";
import { User, UpdateUserPayload } from "@/app/features/users/types";

const { Title, Text } = Typography;

export default function AdminUsersPage() {
  
  const [skip, setSkip] = useState(0);
  const [limit, setLimit] = useState(10);
  const [searchQuery, setSearchQuery] = useState("");

  const [editModalOpen, setEditModalOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  const [getUsers, usersData, loadingUsers] = useGetUsersApi();
  const [updateUser, , updatingUser] = useUpdateUserApi();
  const [deleteUser, , deletingUser] = useDeleteUserApi();

  const fetchUsers = () => {
    getUsers({
      params: {
        skip: skip,
        limit: limit,
      },
    });
  };

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, limit]);

  const rawUsersList = useMemo(() => {
    if (Array.isArray(usersData)) {
      return usersData;
    }
    const responsePayload = usersData as any;
    if (Array.isArray(responsePayload?.data)) {
      return responsePayload.data;
    }
    if (Array.isArray(responsePayload?.users)) {
      return responsePayload.users;
    }
    return [];
  }, [usersData]);

  const totalCount = useMemo(() => {
    const responsePayload = usersData as any;
    if (typeof responsePayload?.total === "number") {
      return responsePayload.total;
    }
    if (typeof responsePayload?.count === "number") {
      return responsePayload.count;
    }
    return rawUsersList.length;
  }, [usersData, rawUsersList]);

  const filteredUsers = useMemo(() => {
    if (!searchQuery) return rawUsersList;
    const query = searchQuery.toLowerCase();
    return rawUsersList.filter((user: User) => {
      const fullName = `${user.first_name || ""} ${user.last_name || ""}`.toLowerCase();
      return (
        fullName.includes(query) ||
        user.email?.toLowerCase().includes(query) ||
        user.username?.toLowerCase().includes(query)
      );
    });
  }, [rawUsersList, searchQuery]);

  const handleEditClick = (user: User) => {
    setSelectedUser(user);
    setEditModalOpen(true);
  };

  const handleEditSubmit = async (values: UpdateUserPayload) => {
    if (!selectedUser?.id) return;
    const response = await updateUser({
      path: `/${selectedUser.id}`,
      data: values,
    });
    if (response) {
      setEditModalOpen(false);
      setSelectedUser(null);
      fetchUsers();
    }
  };

  const handleDeleteClick = (user: User) => {
    Modal.confirm({
      title: "Delete User Account?",
      icon: <InfoCircleOutlined className="text-red-500" />,
      content: `Are you sure you want to permanently delete user ${user.first_name || ""} ${
        user.last_name || ""
      }? This action cannot be undone.`,
      okText: "Yes, Delete",
      okType: "danger",
      cancelText: "Cancel",
      okButtonProps: { className: "!rounded-xl !font-bold" },
      cancelButtonProps: { className: "!rounded-xl !font-bold" },
      centered: true,
      onOk: async () => {
        const response = await deleteUser({
          path: `/${user.id}`,
        });
        if (response) {
          fetchUsers();
        }
      },
    });
  };

  const handlePaginationChange = (page: number, pageSize: number) => {
    setLimit(pageSize);
    setSkip((page - 1) * pageSize);
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 pb-24 relative min-h-screen">
      <Flex vertical gap={40}>
        <Row justify="space-between" align="middle" gutter={[16, 24]}>
          <Col xs={24} md={18}>
            <Flex align="center" gap={12}>
              <Title level={1} className="!m-0 !font-extrabold !text-3xl sm:!text-4xl tracking-tight text-[var(--app-text)]">
                User Management
              </Title>
              <Badge
                count={`${totalCount} users`}
                style={{
                  backgroundColor: "var(--app-active-bg)",
                  color: "#0fb5a1",
                  borderColor: "transparent",
                  fontWeight: 900,
                  fontSize: 12,
                  padding: "0 12px",
                  height: 28,
                  lineHeight: "28px",
                  borderRadius: 14,
                }}
                className="mt-1"
              />
            </Flex>
            <Text className="block mt-2 text-sm sm:text-base text-[var(--app-text-soft)] font-medium">
              Manage user accounts, access privileges, and statuses.
            </Text>
          </Col>
          <Col xs={24} md={6} className="text-right">
            <Button
              type="primary"
              size="large"
              icon={<ReloadOutlined />}
              onClick={fetchUsers}
              loading={loadingUsers}
              className="!h-12 !px-6 !rounded-2xl !bg-[#0fb5a1] !border-none !font-black !text-sm !uppercase !tracking-widest !shadow-lg hover:!scale-[1.02] transition-all"
            >
              Refresh
            </Button>
          </Col>
        </Row>

        <UserTable
          users={filteredUsers}
          loading={loadingUsers}
          total={totalCount}
          skip={skip}
          limit={limit}
          onEdit={handleEditClick}
          onDelete={handleDeleteClick}
          onPaginationChange={handlePaginationChange}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
      </Flex>

      <UserEditModal
        open={editModalOpen}
        onCancel={() => {
          setEditModalOpen(false);
          setSelectedUser(null);
        }}
        onSubmit={handleEditSubmit}
        user={selectedUser}
        loading={updatingUser}
      />
    </div>
  );
}
