"use server";

import { readJsonObject, writeJsonAtomic, pushToQueue } from "@/lib/bot-utils";
import { revalidatePath } from "next/cache";
import type { PuanConfig } from "@/lib/types";
import { DEFAULT_PUAN_CONFIG } from "@/lib/types";

export async function savePuanConfig(formData: FormData) {
  const current = readJsonObject<PuanConfig>("puan_config.json", DEFAULT_PUAN_CONFIG);

  const updated: PuanConfig = {
    voice: {
      puan_per_minute: parseFloat(formData.get("puan_per_minute") as string) || 0.1,
      daily_max: parseFloat(formData.get("daily_max") as string) || 20,
      warning_threshold: parseInt(formData.get("warning_threshold") as string) || 120,
      kick_threshold: parseInt(formData.get("kick_threshold") as string) || 240,
    },
    content: {
      default_base_points: parseFloat(formData.get("content_base") as string) || 0,
      default_loot_bonus_points: parseFloat(formData.get("content_loot") as string) || 0,
    },
    mass: {
      default_base_points: parseFloat(formData.get("mass_base") as string) || 0,
      default_loot_bonus_points: parseFloat(formData.get("mass_loot") as string) || 0,
    },
  };

  void current;
  writeJsonAtomic("puan_config.json", updated);
  revalidatePath("/puan");
}

export async function resetAllPoints(requestedByName: string, requestedById?: string) {
  await pushToQueue("reset_points", {
    requested_by: requestedById ? Number(requestedById) : undefined,
    requested_by_name: requestedByName,
  });
  revalidatePath("/puan");
}
