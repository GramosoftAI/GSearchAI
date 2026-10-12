import { NextResponse } from "next/server";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { name, email, subject, category, message, workspace } = body;

    if (!email || !message) {
      return NextResponse.json(
        { error: "Email and message are required." },
        { status: 400 }
      );
    }

    // Generate a support ticket ID
    const ticketId = `GS-${Date.now().toString(36).toUpperCase()}`;

    console.log(`[SUPPORT TICKET ${ticketId}] Received from ${email} (${name || "Anonymous"}):`, {
      category,
      subject,
      workspace,
      message,
      timestamp: new Date().toISOString(),
    });

    return NextResponse.json({
      success: true,
      ticketId,
      message: "Support request received successfully. Our team will respond within 2 business days.",
    });
  } catch (error: any) {
    console.error("Support API error:", error);
    return NextResponse.json(
      { error: "Failed to process support request. Please email gsearchai@gmail.com directly." },
      { status: 500 }
    );
  }
}
