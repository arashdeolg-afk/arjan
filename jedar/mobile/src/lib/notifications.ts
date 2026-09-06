/**
 * Pure notification helpers. No Expo imports here so they can be unit tested;
 * notificationService.ts wires them to expo-notifications.
 */
export const REMINDER_IDENTIFIER = "jedar-daily-reflection";
export const REMINDER_CHANNEL_ID = "daily-reflection";
export const REMINDER_TITLE = "Your Jedar reflection is ready";
export const REMINDER_BODY = "Take a quiet moment for today’s reflection.";

export type DailyTrigger = { type: "daily"; hour: number; minute: number; channelId: string };
export type ReminderContent = { title: string; body: string; data: { screen: "today" }; sound: boolean };
export type PermissionStatus = "granted" | "denied" | "undetermined";

export function isValidTime(hour: number, minute: number): boolean {
  return Number.isInteger(hour) && Number.isInteger(minute) && hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
}

/** Trigger for expo-notifications' DAILY schedulable trigger, fired in the device's local timezone. */
export function buildDailyTrigger(hour: number, minute: number): DailyTrigger {
  if (!isValidTime(hour, minute)) throw new RangeError(`Invalid reminder time ${hour}:${minute}`);
  return { type: "daily", hour, minute, channelId: REMINDER_CHANNEL_ID };
}

/** Privacy-friendly content: never includes journal text, transcripts, or the reflection itself. */
export function buildReminderContent(): ReminderContent {
  return { title: REMINDER_TITLE, body: REMINDER_BODY, data: { screen: "today" }, sound: false };
}

/** The next local date-time at hour:minute strictly after `now`. */
export function nextReminderDate(now: Date, hour: number, minute: number): Date {
  if (!isValidTime(hour, minute)) throw new RangeError(`Invalid reminder time ${hour}:${minute}`);
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hour, minute, 0, 0);
  if (next.getTime() <= now.getTime()) next.setDate(next.getDate() + 1);
  return next;
}

export function formatReminderTime(hour: number, minute: number, locale?: string): string {
  const d = new Date(2000, 0, 1, hour, minute);
  return d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

/** Accepts "7:30", "07:30", "7:30 pm", "19:30", "7pm". */
export function parseTimeInput(text: string): { hour: number; minute: number } | null {
  const m = /^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\s*$/i.exec(text);
  if (!m) return null;
  let hour = Number(m[1]);
  const minute = m[2] ? Number(m[2]) : 0;
  const suffix = m[3]?.toLowerCase().replace(/\./g, "");
  if (suffix) {
    if (hour < 1 || hour > 12) return null;
    if (suffix === "pm" && hour !== 12) hour += 12;
    if (suffix === "am" && hour === 12) hour = 0;
  }
  return isValidTime(hour, minute) ? { hour, minute } : null;
}

export const TIME_PRESETS: ReadonlyArray<{ hour: number; minute: number }> = [
  { hour: 6, minute: 30 },
  { hour: 8, minute: 0 },
  { hour: 12, minute: 30 },
  { hour: 20, minute: 0 },
];

export type ReminderPlan = { enabled: boolean; hour: number; minute: number };

/** Decide what the scheduler should do when preferences change. */
export function planAction(prev: ReminderPlan | null, next: ReminderPlan): "schedule" | "cancel" | "none" {
  if (!next.enabled) return prev?.enabled ? "cancel" : "none";
  if (!prev || !prev.enabled) return "schedule";
  return prev.hour !== next.hour || prev.minute !== next.minute ? "schedule" : "none";
}

export function permissionLabel(status: PermissionStatus): string {
  switch (status) {
    case "granted":
      return "Allowed";
    case "denied":
      return "Not allowed. Enable notifications for Jedar in your device settings.";
    default:
      return "Not asked yet";
  }
}

/** Data attached to a notification tap; anything else is ignored. */
export function routeForNotificationData(data: unknown): "/(tabs)/today" | null {
  if (data && typeof data === "object" && (data as { screen?: unknown }).screen === "today") return "/(tabs)/today";
  return null;
}
