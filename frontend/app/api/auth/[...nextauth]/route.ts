import NextAuth from "next-auth";
import GoogleProvider from "next-auth/providers/google";
import AzureADProvider from "next-auth/providers/azure-ad";
export const authOptions = {
  providers: [
    GoogleProvider({
      id: "google",
      name: "Google",
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
      authorization: {
        params: {
          scope:
            "openid email profile https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.labels",
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
        },
      },
    }),
  ],
  // AzureADProvider({
  //     clientId: process.env.AZURE_AD_CLIENT_ID!,
  //     clientSecret: process.env.AZURE_AD_CLIENT_SECRET!,
  //     tenantId: process.env.AZURE_AD_TENANT_ID!,
  //   }),
  // ],
callbacks: {
  async jwt({ token, account }: any) {
    console.log("sdrfgthysrduhjgfdsfghj",account?.refresh_token)
    if (account) {
      token.accessToken = account.access_token;
      token.refreshToken = account.refresh_token;
      token.email = token.email;
    }
    if (account?.provider === "azure-ad") {
        token.sharepointAccessToken = account.access_token;
      }
    return token;
  },
  
  async session({ session, token }: any) {
     console.log("sdrfgthysrduhjgfdsfghj",token.refresh_token)
    session.accessToken = token.accessToken;
    session.refreshToken = token.refreshToken;
    session.user.email = token.email;
    session.googleAccessToken = token.googleAccessToken;
    session.sharepointAccessToken = token.sharepointAccessToken;

    return session;
  },
}
  // callbacks: {
  //   async jwt({ token, account }: any) {
  //      console.log("JWT Callback");
  //   console.log("Account:", account);

  //     if (account) {
  //       token.accessToken = account.access_token;
  //        console.log("Access Token:", account.access_token);
  //     }

  //     return token;
  //   },

  //   async session({ session, token }: any) {
  //     console.log("Session Callback");
  //   console.log("Token:", token);
  //     session.accessToken = token.accessToken;
  //     console.log("Session:", session);
  //     return session;
  //   },
  // },
};

const handler = NextAuth(authOptions);

export { handler as GET, handler as POST };
