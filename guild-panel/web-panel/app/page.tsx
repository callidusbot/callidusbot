import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { redirect } from "next/navigation";
import ForbiddenPage from "@/components/ForbiddenPage";
import { readJson } from "@/lib/bot-utils";
import type { ActiveEvent, DynamicSheet, ContentTemplate } from "@/lib/types";
import DashboardClient from "@/components/DashboardClient";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const session = await getServerSession(authOptions);

  if (!session) redirect("/auth/signin");
  if (!session.user?.allowed) return <ForbiddenPage />;

  const events = readJson<ActiveEvent[]>("active_events.json") ?? [];
  const sheets = readJson<DynamicSheet[]>("dynamic_sheets.json") ?? [];
  const templates = readJson<ContentTemplate[]>("content_templates.json") ?? [];

  const activeEvents = Array.isArray(events)
    ? events.filter((e) => e.status === "active")
    : [];
  const totalSheets = Array.isArray(sheets) ? sheets.length : 0;
  const totalTemplates = Array.isArray(templates) ? templates.length : 0;

  return (
    <DashboardClient
      activeEvents={activeEvents}
      totalSheets={totalSheets}
      totalTemplates={totalTemplates}
      user={{
        discordId: session.user.discordId,
        name: session.user.name ?? "Unknown",
      }}
    />
  );
}
