"use server";

import { pushToQueue } from "@/lib/bot-utils";
import { revalidatePath } from "next/cache";

interface CloseContentPayload {
  event_id: string;
  thread_id: number;
  start_loot: boolean;
  requested_by?: number;
  requested_by_name?: string;
}

export async function closeContentAction(payload: CloseContentPayload) {
  await pushToQueue("close_content", {
    event_id: payload.event_id,
    thread_id: payload.thread_id,
    start_loot: payload.start_loot,
    requested_by: payload.requested_by,
    requested_by_name: payload.requested_by_name ?? "Panel",
  });
  revalidatePath("/");
}
