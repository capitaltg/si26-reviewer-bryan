import { auth, signOut } from "@/auth";

export async function AppHeader() {
  const session = await auth();
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-8 py-3">
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- plain <a>
            is required here so this async server component keeps rendering
            correctly under renderToStaticMarkup in app-header.test.tsx */}
        <a
          href="/"
          className="text-sm font-semibold tracking-tight text-slate-900"
        >
          AI Proposal Review Board
        </a>
        {session && (
          <form
            action={async () => {
              "use server";
              await signOut();
            }}
          >
            <button
              type="submit"
              className="text-sm text-slate-500 hover:text-slate-800"
            >
              Sign out
              {session.user?.email && (
                <span className="text-slate-400"> ({session.user.email})</span>
              )}
            </button>
          </form>
        )}
      </div>
    </header>
  );
}
