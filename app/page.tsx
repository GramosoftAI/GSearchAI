"use client"

import { useSession } from "next-auth/react"
import HomePage from "./home/page";

export default function Home() {
  return (
    <div>
      <HomePage />
    </div>
  )
}