import type { NextAuthOptions } from "next-auth";
import DiscordProvider from "next-auth/providers/discord";

export const ALLOWED_ROLES: Record<string, string> = {
  "1419664184261611542": "Guild Master",
  "1419393005978386463": "Subaylar",
  "1427410524693467269": "Recruiter",
  "1419664064149454941": "Content Creator",
};

export const authOptions: NextAuthOptions = {
  providers: [
    DiscordProvider({
      clientId: process.env.DISCORD_CLIENT_ID!,
      clientSecret: process.env.DISCORD_CLIENT_SECRET!,
      authorization: {
        params: {
          scope: "identify guilds guilds.members.read",
        },
      },
    }),
  ],
  secret: process.env.NEXTAUTH_SECRET,
  pages: {
    signIn: "/auth/signin",
    error: "/auth/error",
  },
  callbacks: {
    async jwt({ token, account }) {
      if (account?.access_token) {
        token.accessToken = account.access_token;
      }
      return token;
    },
    async session({ session, token }) {
      const guildId = process.env.DISCORD_GUILD_ID;
      if (!guildId || !token.accessToken) {
        session.user = { ...session.user, allowed: false, roles: [] };
        return session;
      }

      try {
        const res = await fetch(
          `https://discord.com/api/v10/users/@me/guilds/${guildId}/member`,
          {
            headers: { Authorization: `Bearer ${token.accessToken}` },
          }
        );

        if (!res.ok) {
          session.user = { ...session.user, allowed: false, roles: [] };
          return session;
        }

        const member = await res.json();
        const memberRoles: string[] = member.roles ?? [];

        const matchedRoles = memberRoles
          .filter((r) => ALLOWED_ROLES[r])
          .map((r) => ALLOWED_ROLES[r]);

        const allowed = matchedRoles.length > 0;

        session.user = {
          ...session.user,
          discordId: token.sub,
          allowed,
          roles: matchedRoles,
        };
      } catch {
        session.user = { ...session.user, allowed: false, roles: [] };
      }

      return session;
    },
  },
};

declare module "next-auth" {
  interface Session {
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      discordId?: string;
      allowed?: boolean;
      roles?: string[];
    };
  }
}
