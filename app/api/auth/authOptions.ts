import GoogleProvider from "next-auth/providers/google";
import AzureADProvider from "next-auth/providers/azure-ad";
import { AuthOptions } from "next-auth";

export const authOptions: AuthOptions = {
  providers: [
    // 1. Dedicated Google Drive Provider (Only Drive scopes)
    GoogleProvider({
      id: "google-drive",
      name: "Google Drive",
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      authorization: {
        params: {
          scope:
            "openid email profile https://www.googleapis.com/auth/drive.readonly",
          access_type: "offline",
          prompt: "consent",
        },
      },
    }),

    // 2. Dedicated Gmail Provider (Only Gmail scopes)
    GoogleProvider({
      id: "google-gmail",
      name: "Gmail",
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      authorization: {
        params: {
          scope:
            "openid email profile https://www.googleapis.com/auth/gmail.readonly",
          access_type: "offline",
          prompt: "consent",
        },
      },
    }),

    AzureADProvider({
      clientId: process.env.AZURE_AD_CLIENT_ID!,
      clientSecret: process.env.AZURE_AD_CLIENT_SECRET!,
      tenantId: "common",
      authorization: {
        params: {
          scope:
            "openid profile email offline_access User.Read Files.Read.All Mail.Read",
          prompt: "select_account",
        },
      },
    }),
  ],
  callbacks: {
    async jwt({ token, account }: any) {
      if (account) {
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.provider = account.provider;
        token.email = token.email;
      }
      if (account?.provider === "azure-ad") {
        token.sharepointAccessToken = account.access_token;
      }
      return token;
    },
    async session({ session, token }: any) {
      session.accessToken = token.accessToken;
      session.refreshToken = token.refreshToken;
      session.provider = token.provider;
      if (session.user) {
        session.user.email = token.email;
      }
      session.googleAccessToken = token.googleAccessToken;
      session.sharepointAccessToken = token.sharepointAccessToken;
      return session;
    },
  },
};
