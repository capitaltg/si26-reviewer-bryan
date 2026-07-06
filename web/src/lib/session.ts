import { auth } from "@/auth";

export async function getUserId(): Promise<string | null> {
  const session = await auth();
  return session?.userId ?? null;
}
