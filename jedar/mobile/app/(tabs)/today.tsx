import { useCallback, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { ReflectionCard } from "@/src/components/ReflectionCard";
import { Button } from "@/src/components/Button";
import { Body, Caption, Title } from "@/src/components/Typography";
import { fetchTodayReflection } from "@/src/lib/api";
import { friendlyDate, localDateString } from "@/src/lib/dates";
import { formatReminderTime } from "@/src/lib/notifications";
import type { PublicReflection } from "@/src/lib/domain";
import { useApp } from "@/src/state/AppContext";
import { colors, spacing } from "@/src/theme/tokens";

export default function Today() {
  const router = useRouter();
  const { prefs, journal } = useApp();
  const [reflection, setReflection] = useState<PublicReflection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!prefs.faith) return;
    setLoading(true);
    setError(null);
    try {
      const { reflection: r } = await fetchTodayReflection(prefs.faith, localDateString(), prefs.installId);
      setReflection(r);
      setSaved(!!(await journal?.findByReflection(r.id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the Jedar server");
    } finally {
      setLoading(false);
    }
  }, [prefs.faith, prefs.installId, journal]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const save = async () => {
    if (!reflection || !journal || saved) return;
    setSaving(true);
    try {
      const body =
        reflection.label === "Scripture" && reflection.sourceName && reflection.reference
          ? `${reflection.body}\n\n${reflection.sourceName}, ${reflection.reference}`
          : reflection.body;
      await journal.create({ type: "reflection", title: reflection.title, body, faith: reflection.faith, reflectionId: reflection.id });
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen scroll>
      <Caption style={styles.date}>{friendlyDate()}</Caption>
      <Title>Today</Title>
      <Body muted style={styles.lead}>
        A quiet moment before the day fills up.
      </Body>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.gold} />
        </View>
      ) : error ? (
        <View style={styles.errorBox}>
          <Body center>Jedar couldn’t load today’s reflection.</Body>
          <Caption center>{error}</Caption>
          <Button title="Try again" variant="secondary" onPress={load} compact />
        </View>
      ) : reflection ? (
        <ReflectionCard
          reflection={reflection}
          saved={saved}
          saving={saving}
          onSave={save}
          onTalk={() => router.push({ pathname: "/(tabs)/voice", params: { reflectionId: reflection.id } })}
        />
      ) : null}

      <Pressable onPress={() => router.navigate("/(tabs)/settings")} style={styles.reminder} accessibilityRole="button" accessibilityLabel="Daily reminder settings">
        <View style={[styles.dot, { backgroundColor: prefs.reminderEnabled ? colors.mint : colors.textFaint }]} />
        <Caption>
          {prefs.reminderEnabled ? `Daily reminder at ${formatReminderTime(prefs.reminderHour, prefs.reminderMinute)}` : "Daily reminder is off"}
        </Caption>
      </Pressable>
    </Screen>
  );
}

const styles = StyleSheet.create({
  date: { marginTop: spacing.sm, color: colors.gold },
  lead: { marginTop: spacing.xs, marginBottom: spacing.xl },
  center: { paddingVertical: spacing.huge, alignItems: "center" },
  errorBox: { gap: spacing.md, paddingVertical: spacing.xl, alignItems: "center" },
  reminder: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xl, alignSelf: "center" },
  dot: { width: 8, height: 8, borderRadius: 4 },
});
