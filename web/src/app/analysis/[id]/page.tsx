import { redirect } from "next/navigation";
import { auth } from "@/auth";
import { StatusView } from "./status-view";

export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth();
  if (!session) redirect("/");
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 p-8">
      <h1 className="mb-6 text-xl font-semibold">Analysis</h1>
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <StatusView analysisId={id} />
      </div>
    </main>
  );
}
