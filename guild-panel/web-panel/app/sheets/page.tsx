import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import ForbiddenPage from "@/components/ForbiddenPage";
import { readJson } from "@/lib/bot-utils";
import type { DynamicSheet } from "@/lib/types";
import SheetsClient from "@/components/SheetsClient";

export const dynamic = "force-dynamic";

export default async function SheetsPage() {
  const session = await getServerSession(authOptions);
  if (!session) redirect("/auth/signin");
  if (!session.user?.allowed) return <ForbiddenPage />;

  const raw = readJson<DynamicSheet[]>("dynamic_sheets.json");
  const sheets = Array.isArray(raw) ? raw : [];

  return <SheetsClient sheets={sheets} />;
}
