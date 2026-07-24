"use client";

import { Flex } from "antd";
import ForgotPasswordForm from "../../features/auth/components/ForgotPasswordForm";

export default function ForgotPasswordPage() {
  return (
    <Flex justify="center" align="center" className="min-h-screen">
      <ForgotPasswordForm />
    </Flex>
  );
}
