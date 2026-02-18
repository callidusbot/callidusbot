import fs from "fs";
import path from "path";

const DATA_PATH = process.env.BOT_DATA_PATH ?? "../data";
const COMMANDS_PATH = process.env.BOT_COMMANDS_PATH ?? "../bot_commands";

function resolvePath(base: string, filename: string): string {
  return path.resolve(process.cwd(), base, filename);
}

export function readJson<T = unknown>(filename: string): T {
  try {
    const filePath = resolvePath(DATA_PATH, filename);
    if (!fs.existsSync(filePath)) return (Array.isArray([]) ? [] : {}) as T;
    const raw = fs.readFileSync(filePath, "utf-8").trim();
    if (!raw) return ([] as unknown) as T;
    return JSON.parse(raw) as T;
  } catch {
    return ([] as unknown) as T;
  }
}

export function readJsonObject<T extends object>(filename: string, fallback: T): T {
  try {
    const filePath = resolvePath(DATA_PATH, filename);
    if (!fs.existsSync(filePath)) return fallback;
    const raw = fs.readFileSync(filePath, "utf-8").trim();
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJsonAtomic(filename: string, data: unknown): void {
  const filePath = resolvePath(DATA_PATH, filename);
  const tmpPath = filePath + ".tmp";
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), "utf-8");
  fs.renameSync(tmpPath, filePath);
}

export async function pushToQueue(
  action: string,
  payload: Record<string, unknown>
): Promise<void> {
  const queuePath = resolvePath(COMMANDS_PATH, "queue.jsonl");
  const queueDir = path.dirname(queuePath);
  if (!fs.existsSync(queueDir)) {
    fs.mkdirSync(queueDir, { recursive: true });
  }

  const line =
    JSON.stringify({
      action,
      ...payload,
      ts: Math.floor(Date.now() / 1000),
    }) + "\n";

  const maxAttempts = 5;
  const backoff = [300, 350, 400, 450, 500];

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      fs.appendFileSync(queuePath, line, "utf-8");
      return;
    } catch (err) {
      if (attempt < maxAttempts - 1) {
        await new Promise((res) => setTimeout(res, backoff[attempt]));
      } else {
        throw err;
      }
    }
  }
}
