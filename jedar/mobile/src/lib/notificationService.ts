import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import {
  REMINDER_CHANNEL_ID,
  REMINDER_IDENTIFIER,
  buildDailyTrigger,
  buildReminderContent,
  planAction,
  routeForNotificationData,
  type PermissionStatus,
  type ReminderPlan,
} from "./notifications";

let configured = false;

/** Foreground presentation and the Android channel. Safe to call repeatedly. */
export async function configureNotifications(): Promise<void> {
  if (configured) return;
  configured = true;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
  });
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync(REMINDER_CHANNEL_ID, {
      name: "Daily reflection",
      importance: Notifications.AndroidImportance.DEFAULT,
      vibrationPattern: [0, 120],
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
    });
  }
}

function toStatus(p: Notifications.NotificationPermissionsStatus): PermissionStatus {
  if (p.granted || p.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL) return "granted";
  return p.canAskAgain && p.status === "undetermined" ? "undetermined" : "denied";
}

export async function getPermissionStatus(): Promise<PermissionStatus> {
  try {
    return toStatus(await Notifications.getPermissionsAsync());
  } catch {
    return "denied";
  }
}

/** Only call after the user has read what reminders do and tapped to enable them. */
export async function requestPermission(): Promise<PermissionStatus> {
  try {
    return toStatus(await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowSound: false, allowBadge: false } }));
  } catch {
    return "denied";
  }
}

export async function scheduleDailyReminder(hour: number, minute: number): Promise<void> {
  await configureNotifications();
  await cancelDailyReminder();
  const trigger = buildDailyTrigger(hour, minute);
  await Notifications.scheduleNotificationAsync({
    identifier: REMINDER_IDENTIFIER,
    content: buildReminderContent(),
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DAILY,
      hour: trigger.hour,
      minute: trigger.minute,
      ...(Platform.OS === "android" ? { channelId: trigger.channelId } : {}),
    },
  });
}

export async function cancelDailyReminder(): Promise<void> {
  try {
    await Notifications.cancelScheduledNotificationAsync(REMINDER_IDENTIFIER);
  } catch {
    // nothing scheduled
  }
}

export async function isReminderScheduled(): Promise<boolean> {
  try {
    const all = await Notifications.getAllScheduledNotificationsAsync();
    return all.some((n) => n.identifier === REMINDER_IDENTIFIER);
  } catch {
    return false;
  }
}

/**
 * Reconcile the OS schedule with preferences. Never requests permission itself;
 * returns "denied" so the UI can explain without breaking anything.
 */
export async function applyReminderPlan(prev: ReminderPlan | null, next: ReminderPlan): Promise<"scheduled" | "cancelled" | "unchanged" | "denied"> {
  const action = planAction(prev, next);
  if (action === "none") {
    if (next.enabled && !(await isReminderScheduled())) {
      if ((await getPermissionStatus()) !== "granted") return "denied";
      await scheduleDailyReminder(next.hour, next.minute);
      return "scheduled";
    }
    return "unchanged";
  }
  if (action === "cancel") {
    await cancelDailyReminder();
    return "cancelled";
  }
  if ((await getPermissionStatus()) !== "granted") return "denied";
  await scheduleDailyReminder(next.hour, next.minute);
  return "scheduled";
}

/** Route to open when a notification is tapped; the tap payload is validated, never trusted blindly. */
export function addNotificationTapListener(onRoute: (route: "/(tabs)/today") => void): () => void {
  const sub = Notifications.addNotificationResponseReceivedListener((response) => {
    const route = routeForNotificationData(response.notification.request.content.data);
    if (route) onRoute(route);
  });
  return () => sub.remove();
}

export async function getColdStartRoute(): Promise<"/(tabs)/today" | null> {
  try {
    const response = await Notifications.getLastNotificationResponseAsync();
    return response ? routeForNotificationData(response.notification.request.content.data) : null;
  } catch {
    return null;
  }
}
