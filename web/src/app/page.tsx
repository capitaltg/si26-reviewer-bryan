import { auth, devLoginEnabled, signIn } from "@/auth";
import { UploadForm } from "./upload-form";

export default async function Home() {
  const session = await auth();
  if (!session) {
    return (
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center p-8">
        <div className="space-y-6 rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
          <div className="space-y-1 text-center">
            <h1 className="text-lg font-semibold">AI Proposal Review Board</h1>
            <p className="text-sm text-slate-500">
              Sign in to run a proposal review.
            </p>
          </div>
          <form
            action={async () => {
              "use server";
              await signIn("keycloak");
            }}
          >
            <button className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
              Sign in with Keycloak
            </button>
          </form>
          {devLoginEnabled && (
            <form
              action={async (formData: FormData) => {
                "use server";
                await signIn("credentials", formData);
              }}
              className="space-y-2 border-t border-slate-200 pt-4"
            >
              <input
                name="email"
                type="email"
                required
                placeholder="Email"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
              <button className="w-full rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50">
                Dev sign-in
              </button>
            </form>
          )}
        </div>
      </main>
    );
  }
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 p-8">
      <div>
        <h1 className="text-xl font-semibold">New analysis</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload a solicitation and proposal deck to run the review pipeline.
        </p>
      </div>
      <UploadForm />
    </main>
  );
}
