/** YYYY-MM-DD in the device's local timezone (never UTC, so "today" matches the user). */
export function localDateString(date: Date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function formatTimestamp(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay = localDateString(date) === localDateString(now);
  const time = date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `Today, ${time}`;
  const day = date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: date.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  return `${day}, ${time}`;
}

export function friendlyDate(date: Date = new Date()): string {
  return date.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}
