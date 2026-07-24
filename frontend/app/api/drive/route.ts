import { getServerSession } from "next-auth"
import { authOptions } from "../auth/[...nextauth]/route"

export async function GET() {
  const session: any = await getServerSession(authOptions)

  const res = await fetch(
    "https://www.googleapis.com/drive/v3/files",
    {
      headers: {
        Authorization: `Bearer ${session.accessToken}`,
      },
    }
  )

  const data = await res.json()
console.log("daaaaaaaaaaaaaatttttttttttttaaaaaaaa",data);
  return Response.json(data)
}