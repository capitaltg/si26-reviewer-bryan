import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";
import Credentials from "next-auth/providers/credentials";
import { db } from "@/db";
import { users } from "@/db/schema";

// Dev-only login for local demoing (no real Keycloak credentials available
// locally). Hard-gated: only registered when explicitly enabled AND never
// in production, regardless of the flag.
export const devLoginEnabled =
  process.env.AUTH_DEV_LOGIN === "true" && process.env.NODE_ENV !== "production";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Keycloak,
    ...(devLoginEnabled
      ? [
          Credentials({
            name: "Dev sign-in",
            credentials: {
              email: { label: "Email", type: "email" },
            },
            async authorize(credentials) {
              const email = credentials?.email;
              if (typeof email !== "string" || email.length === 0) {
                return null;
              }
              const [row] = await db
                .insert(users)
                .values({ keycloakSub: `dev:${email}`, email })
                .onConflictDoUpdate({
                  target: users.keycloakSub,
                  set: { email },
                })
                .returning({ id: users.id });
              return { id: row.id, email };
            },
          }),
        ]
      : []),
  ],
  callbacks: {
    async jwt({ token, profile, account, user }) {
      // First sign-in only: upsert the user, stash our internal id in the JWT.
      if (profile?.sub) {
        const [row] = await db
          .insert(users)
          .values({ keycloakSub: profile.sub, email: profile.email ?? "" })
          .onConflictDoUpdate({
            target: users.keycloakSub,
            set: { email: profile.email ?? "" },
          })
          .returning({ id: users.id });
        token.userId = row.id;
      } else if (account?.provider === "credentials" && user) {
        token.userId = user.id;
      }
      return token;
    },
    async session({ session, token }) {
      return {
        ...session,
        userId: token.userId as string | undefined,
      };
    },
  },
});
