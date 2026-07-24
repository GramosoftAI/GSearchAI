import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(req: NextRequest) {
    const pathname = req.nextUrl.pathname;
    if (pathname.startsWith("/_next") || pathname.startsWith("/api") || pathname.startsWith("/favicon")) {
        return NextResponse.next();
    }
    const publicRoutes = ["/", "/home", "/login", "/register"];
    if (publicRoutes.some(route => pathname === route || pathname === `${route}/`)) {
        return NextResponse.next();
    }
    const key = process.env.AUTH_COOKIE_KEY || "AUTH_TOKEN";
    // const token = req.cookies.get(key)?.value;

    // if (!token) {
    //     const url = req.nextUrl.clone();
    //     url.pathname = "/home";
    //     return NextResponse.redirect(url);
    // }
    return NextResponse.next();
}

export const config = {
    matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};