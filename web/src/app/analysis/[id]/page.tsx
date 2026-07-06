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
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-xl font-semibold">Analysis</h1>
      <StatusView analysisId={id} />
    </main>
  );
}
