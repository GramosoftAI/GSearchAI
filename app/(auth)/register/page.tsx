"use client"
import React, { useState, useEffect } from 'react'
import RegisterForm from "../../features/auth/components/RegisterForm"
import Loader from "@/app/components/provider/Loder"

export default function Page() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setLoading(false);
    }, 2000);
    return () => clearTimeout(timer);
  }, []);

  if (loading) {
    return <Loader />;
  }

  return (
    <RegisterForm/>
  )
}