"use client"
import React, { useState, useEffect } from "react"
import { Flex } from "antd"
import LoginForm from "../../features/auth/components/LoginForm"
import Loader from "@/app/components/provider/Loder"

export default function Login() {
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
        <Flex justify="center" align="center" className="bg-reg-500!">
            <LoginForm />
        </Flex>
    )
}