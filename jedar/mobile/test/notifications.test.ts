import { test } from "node:test";
import assert from "node:assert/strict";
import {
  REMINDER_BODY,
  REMINDER_TITLE,
  buildDailyTrigger,
  buildReminderContent,
  formatReminderTime,
  nextReminderDate,
  parseTimeInput,
  permissionLabel,
  planAction,
  routeForNotificationData,
} from "../src/lib/notifications.js";

test("daily trigger validates ranges", () => {
  assert.deepEqual(buildDailyTrigger(8, 0), { type: "daily", hour: 8, minute: 0, channelId: "daily-reflection" });
  assert.throws(() => buildDailyTrigger(24, 0), RangeError);
  assert.throws(() => buildDailyTrigger(-1, 0), RangeError);
  assert.throws(() => buildDailyTrigger(8, 60), RangeError);
  assert.throws(() => buildDailyTrigger(8.5, 0), RangeError);
});

test("reminder content is privacy friendly", () => {
  const c = buildReminderContent();
  assert.equal(c.title, REMINDER_TITLE);
  assert.equal(c.body, REMINDER_BODY);
  assert.equal(c.title, "Your Jedar reflection is ready");
  assert.match(c.body, /quiet moment/);
  assert.deepEqual(c.data, { screen: "today" });
  assert.equal(c.sound, false);
});

test("next reminder date is today if still ahead, otherwise tomorrow, in local time", () => {
  const now = new Date(2026, 8, 4, 7, 15);
  const later = nextReminderDate(now, 8, 0);
  assert.equal(later.getDate(), 4);
  assert.equal(later.getHours(), 8);
  const earlier = nextReminderDate(now, 6, 30);
  assert.equal(earlier.getDate(), 5);
  assert.equal(earlier.getHours(), 6);
  assert.equal(earlier.getMinutes(), 30);
  const exact = nextReminderDate(new Date(2026, 8, 4, 8, 0, 0), 8, 0);
  assert.equal(exact.getDate(), 5, "an exact match rolls to tomorrow");
  const monthEnd = nextReminderDate(new Date(2026, 8, 30, 23, 0), 8, 0);
  assert.equal(monthEnd.getMonth(), 9);
  assert.equal(monthEnd.getDate(), 1);
});

test("time formatting and parsing", () => {
  assert.equal(formatReminderTime(7, 5, "en-US"), "7:05 AM");
  assert.equal(formatReminderTime(19, 30, "en-US"), "7:30 PM");
  assert.deepEqual(parseTimeInput("7:30"), { hour: 7, minute: 30 });
  assert.deepEqual(parseTimeInput("07:30"), { hour: 7, minute: 30 });
  assert.deepEqual(parseTimeInput("7:30 pm"), { hour: 19, minute: 30 });
  assert.deepEqual(parseTimeInput("12 am"), { hour: 0, minute: 0 });
  assert.deepEqual(parseTimeInput("12:15 p.m."), { hour: 12, minute: 15 });
  assert.deepEqual(parseTimeInput("19:30"), { hour: 19, minute: 30 });
  assert.equal(parseTimeInput("25:00"), null);
  assert.equal(parseTimeInput("13 pm"), null);
  assert.equal(parseTimeInput("soon"), null);
  assert.equal(parseTimeInput(""), null);
});

test("plan action reschedules only when needed", () => {
  assert.equal(planAction(null, { enabled: false, hour: 8, minute: 0 }), "none");
  assert.equal(planAction(null, { enabled: true, hour: 8, minute: 0 }), "schedule");
  assert.equal(planAction({ enabled: true, hour: 8, minute: 0 }, { enabled: true, hour: 8, minute: 0 }), "none");
  assert.equal(planAction({ enabled: true, hour: 8, minute: 0 }, { enabled: true, hour: 9, minute: 0 }), "schedule");
  assert.equal(planAction({ enabled: true, hour: 8, minute: 0 }, { enabled: true, hour: 8, minute: 30 }), "schedule");
  assert.equal(planAction({ enabled: true, hour: 8, minute: 0 }, { enabled: false, hour: 8, minute: 0 }), "cancel");
  assert.equal(planAction({ enabled: false, hour: 8, minute: 0 }, { enabled: false, hour: 9, minute: 0 }), "none");
  assert.equal(planAction({ enabled: false, hour: 8, minute: 0 }, { enabled: true, hour: 8, minute: 0 }), "schedule");
});

test("permission labels and tap routing", () => {
  assert.equal(permissionLabel("granted"), "Allowed");
  assert.match(permissionLabel("denied"), /device settings/);
  assert.equal(permissionLabel("undetermined"), "Not asked yet");
  assert.equal(routeForNotificationData({ screen: "today" }), "/(tabs)/today");
  assert.equal(routeForNotificationData({ screen: "journal" }), null);
  assert.equal(routeForNotificationData(undefined), null);
  assert.equal(routeForNotificationData("today"), null);
});
