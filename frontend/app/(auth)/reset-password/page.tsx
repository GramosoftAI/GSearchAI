"use client";

import { Flex } from "antd";
import ResetPasswordForm from "../../features/auth/components/ResetPasswordForm";

export default function ResetPasswordPage() {
  return (
    <Flex justify="center" align="center" className="min-h-screen">
      <ResetPasswordForm />
    </Flex>
  );
}
