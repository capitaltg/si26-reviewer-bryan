import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { loadReport } from "@/lib/report";

import { ReportView } from "./report-view";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth();
  if (!session?.userId) redirect("/");
  const { id } = await params;

  const result = await loadReport(session.userId, id);
  if (result.kind === "not_found") redirect("/");
  if (result.kind === "not_complete") redirect(`/analysis/${id}`);

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 p-8">
      <h1 className="mb-6 text-xl font-semibold">Analysis report</h1>
      <ReportView model={result.model} analysisId={id} />
    </main>
  );
}
