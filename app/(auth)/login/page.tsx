"use client";

import React, { useState, useEffect } from "react";
import LoginForm from "../../features/auth/components/LoginForm";
import Loader from "@/app/components/provider/Loder";

export default function Login() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  if (loading) {
    return <Loader />;
  }

  return <LoginForm />;
}
