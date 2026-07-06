import { auth, devLoginEnabled, signIn, signOut } from "@/auth";
import { UploadForm } from "./upload-form";

export default async function Home() {
  const session = await auth();
  if (!session) {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <h1 className="mb-6 text-xl font-semibold">AI Proposal Review Board</h1>
        <form
          action={async () => {
            "use server";
            await signIn("keycloak");
          }}
        >
          <button className="rounded bg-black px-4 py-2 text-white">
            Sign in with Keycloak
          </button>
        </form>
        {devLoginEnabled && (
          <form
            action={async (formData: FormData) => {
              "use server";
              await signIn("credentials", formData);
            }}
            className="space-y-2"
          >
            <input
              name="email"
              type="email"
              required
              placeholder="Email"
              className="rounded border px-2 py-1"
            />
            <button className="rounded border px-4 py-2">
              Dev sign-in
            </button>
          </form>
        )}
      </main>
    );
  }
  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">AI Proposal Review Board</h1>
        <form
          action={async () => {
            "use server";
            await signOut();
          }}
        >
          <button className="text-sm underline">
            Sign out ({session.user?.email})
          </button>
        </form>
      </div>
      <UploadForm />
    </main>
  );
}
