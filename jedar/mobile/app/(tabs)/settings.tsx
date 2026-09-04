import { useCallback, useEffect, useState } from "react";
import { Alert, Linking, StyleSheet, Switch, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Card } from "@/src/components/Card";
import { Chip } from "@/src/components/Chip";
import { Button } from "@/src/components/Button";
import { TimePicker } from "@/src/components/TimePicker";
import { Body, Caption, Heading, Label, Title } from "@/src/components/Typography";
import { FAITHS, FAITH_INFO, JEDAR_VOICES, VOICE_INFO } from "@/src/lib/domain";
import { formatReminderTime, permissionLabel, type PermissionStatus } from "@/src/lib/notifications";
import { getPermissionStatus, requestPermission } from "@/src/lib/notificationService";
import { API_URL, checkServer } from "@/src/lib/api";
import { useApp } from "@/src/state/AppContext";
import { colors, spacing } from "@/src/theme/tokens";

export default function Settings() {
  const router = useRouter();
  const { prefs, updatePrefs, deleteAllJournalData, resetApp } = useApp();
  const [permission, setPermission] = useState<PermissionStatus>("undetermined");
  const [server, setServer] = useState<{ ok: boolean; voice: boolean } | null>(null);

  const refreshPermission = useCallback(async () => setPermission(await getPermissionStatus()), []);
  useFocusEffect(
    useCallback(() => {
      void refreshPermission();
    }, [refreshPermission]),
  );
  useEffect(() => {
    checkServer().then(setServer);
  }, []);

  const enableReminders = () => {
    // Explain first; permission is requested only after the user opts in here.
    Alert.alert(
      "Daily reminder",
      `Jedar can send one gentle notification each day at ${formatReminderTime(prefs.reminderHour, prefs.reminderMinute)}. It never includes journal or conversation text. You can turn it off at any time.`,
      [
        { text: "Not now", style: "cancel" },
        {
          text: "Continue",
          onPress: async () => {
            const status = permission === "granted" ? "granted" : await requestPermission();
            setPermission(status);
            if (status === "granted") {
              await updatePrefs({ reminderEnabled: true });
            } else {
              Alert.alert("Notifications are off", "Jedar will work normally without reminders. You can allow notifications for Jedar in your device settings later.", [
                { text: "OK" },
                { text: "Open settings", onPress: () => void Linking.openSettings() },
              ]);
            }
          },
        },
      ],
    );
  };

  const toggleReminders = (value: boolean) => {
    if (value) enableReminders();
    else void updatePrefs({ reminderEnabled: false });
  };

  const confirmDeleteJournal = () => {
    Alert.alert("Delete all journal data?", "Every reflection, note, and saved conversation on this device will be removed. This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete all",
        style: "destructive",
        onPress: async () => {
          const n = await deleteAllJournalData();
          Alert.alert(n === 1 ? "1 entry deleted" : `${n} entries deleted`);
        },
      },
    ]);
  };

  const confirmReset = () => {
    Alert.alert("Start over?", "This clears your faith and voice choices, turns off reminders, and deletes all journal data on this device.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Start over",
        style: "destructive",
        onPress: async () => {
          await resetApp();
          router.replace("/onboarding/welcome");
        },
      },
    ]);
  };

  return (
    <Screen scroll>
      <Title style={styles.title}>Settings</Title>

      <Section label="Faith">
        <View style={styles.chips}>
          {FAITHS.map((f) => (
            <Chip key={f} label={FAITH_INFO[f].label} selected={prefs.faith === f} onPress={() => void updatePrefs({ faith: f })} />
          ))}
        </View>
      </Section>

      <Section label="Jedar’s voice">
        <View style={styles.chips}>
          {JEDAR_VOICES.map((v) => (
            <Chip key={v} label={`${VOICE_INFO[v].label} · ${VOICE_INFO[v].description}`} selected={prefs.voice === v} onPress={() => void updatePrefs({ voice: v })} tone="lavender" />
          ))}
        </View>
      </Section>

      <Section label="Daily reminder">
        <View style={styles.row}>
          <View style={styles.rowText}>
            <Heading>Daily reflection reminder</Heading>
            <Caption>One quiet notification a day. Never includes personal content.</Caption>
          </View>
          <Switch value={prefs.reminderEnabled} onValueChange={toggleReminders} trackColor={{ true: colors.emerald, false: colors.border }} thumbColor={colors.pearl} accessibilityLabel="Daily reminder" />
        </View>
        <Caption style={styles.permission}>Permission: {permissionLabel(permission)}</Caption>
        {permission === "denied" ? <Button title="Open device settings" variant="secondary" compact onPress={() => void Linking.openSettings()} /> : null}
        <View style={styles.picker}>
          <Caption style={styles.pickerLabel}>Reminder time (your local time)</Caption>
          <TimePicker hour={prefs.reminderHour} minute={prefs.reminderMinute} onChange={(hour, minute) => void updatePrefs({ reminderHour: hour, reminderMinute: minute })} />
        </View>
      </Section>

      <Section label="Connection">
        <Body>Server</Body>
        <Caption selectable>{API_URL}</Caption>
        <Caption style={styles.serverStatus}>
          {server === null ? "Checking…" : !server.ok ? "Not reachable. Check EXPO_PUBLIC_API_URL and that the server is running." : server.voice ? "Connected. Voice is configured." : "Connected. Voice is not configured on the server (no API key); text still works."}
        </Caption>
        <Caption style={styles.note}>Live voice needs a development build with react-native-webrtc. Expo Go can show the app but cannot run voice conversations.</Caption>
      </Section>

      <Section label="About Jedar">
        <Body>Jedar is a supportive companion for reflection, prayer, journaling, and learning within your faith.</Body>
        <Caption style={styles.note}>
          Jedar is not a deity, prophet, clergy member, therapist, or religious authority, and it never replaces qualified human guidance. For rulings or disputed interpretations, speak with clergy or scholars in your tradition. If you are in danger, contact local emergency services.
        </Caption>
      </Section>

      <Section label="Privacy">
        <Caption style={styles.note}>Your journal stays on this device. Voice transcripts are never saved unless you choose to keep a conversation. The server only receives what you say during a conversation and never stores it.</Caption>
        <Button title="Delete all journal data" variant="danger" onPress={confirmDeleteJournal} style={styles.dangerBtn} />
        <Button title="Start over" variant="ghost" onPress={confirmReset} compact />
      </Section>
    </Screen>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card style={styles.section}>
      <Label style={styles.sectionLabel}>{label}</Label>
      {children}
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { marginTop: spacing.sm, marginBottom: spacing.lg },
  section: { marginBottom: spacing.lg, gap: spacing.md },
  sectionLabel: { marginBottom: spacing.xs },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  rowText: { flex: 1, gap: 2 },
  permission: { color: colors.textFaint },
  picker: { marginTop: spacing.sm, gap: spacing.md },
  pickerLabel: { color: colors.textMuted },
  serverStatus: { color: colors.mint },
  note: { color: colors.textFaint },
  dangerBtn: { marginTop: spacing.sm },
});
