import { getServerSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
  }
}
export async function GET() {
  const session = await getServerSession();

  const response = await fetch(
    "https://graph.microsoft.com/v1.0/me/drive/root/children",
    {
      headers: {
        Authorization: `Bearer ${session?.accessToken}`,
      },
    }
  );

  const data = await response.json();

  return Response.json(data);
}