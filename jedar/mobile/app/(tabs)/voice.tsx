import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Orb } from "@/src/components/Orb";
import { Chip } from "@/src/components/Chip";
import { Button } from "@/src/components/Button";
import { Composer } from "@/src/components/Composer";
import { TranscriptPanel } from "@/src/components/TranscriptPanel";
import { Body, Caption, Heading } from "@/src/components/Typography";
import { FAITH_INFO, MODES, MODE_INFO, VOICE_INFO, type Mode, type PublicReflection } from "@/src/lib/domain";
import { fetchReflection, type VoiceSelection } from "@/src/lib/api";
import { STATUS_LABELS } from "@/src/lib/realtimeEvents";
import { useVoiceSession } from "@/src/lib/useVoiceSession";
import { formatConversation } from "@/src/lib/journal";
import { useApp } from "@/src/state/AppContext";
import { colors, radius, spacing } from "@/src/theme/tokens";

export default function Voice() {
  const router = useRouter();
  const { prefs, journal } = useApp();
  const params = useLocalSearchParams<{ reflectionId?: string }>();
  const reflectionId = typeof params.reflectionId === "string" && params.reflectionId ? params.reflectionId : undefined;
  const [mode, setMode] = useState<Mode>("calm");
  const [reflection, setReflection] = useState<PublicReflection | null>(null);
  const { state, start, end, sendText, clear } = useVoiceSession(prefs.installId);

  useEffect(() => {
    let cancelled = false;
    if (!reflectionId) {
      setReflection(null);
      return;
    }
    fetchReflection(reflectionId, prefs.installId)
      .then((r) => {
        if (!cancelled) setReflection(r);
      })
      .catch(() => {
        if (!cancelled) setReflection(null);
      });
    return () => {
      cancelled = true;
    };
  }, [reflectionId, prefs.installId]);

  // Leaving the tab ends the conversation so the microphone never runs unnoticed.
  useFocusEffect(
    useCallback(() => {
      return () => end();
    }, [end]),
  );

  const selection = useMemo<VoiceSelection>(
    () => ({ faith: prefs.faith ?? "sikh", mode, voice: prefs.voice, reflectionId: reflection ? reflection.id : undefined }),
    [prefs.faith, prefs.voice, mode, reflection],
  );

  const live = state.status !== "idle";
  const dismissReflection = () => router.setParams({ reflectionId: "" });

  const saveConversation = () => {
    const lines = state.transcript.filter((e) => e.final && e.text.trim());
    if (!journal || !prefs.faith || lines.length === 0) return;
    const faith = prefs.faith;
    Alert.alert("Save this conversation?", "The transcript will be stored privately on this device in your journal. Nothing is uploaded.", [
      { text: "Not now", style: "cancel" },
      {
        text: "Save",
        onPress: async () => {
          const title = reflection ? `On “${reflection.title}”` : `${MODE_INFO[mode].label} conversation`;
          await journal.create({ type: "conversation", title, body: formatConversation(lines), faith, reflectionId: reflection?.id });
          Alert.alert("Saved to your journal");
        },
      },
    ]);
  };

  return (
    <Screen padded={false} glow="center">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.fill} keyboardVerticalOffset={80}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
          <View style={styles.topRow}>
            <Caption>{prefs.faith ? FAITH_INFO[prefs.faith].label : ""}</Caption>
            <Caption>Voice · {VOICE_INFO[prefs.voice].label}</Caption>
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {MODES.map((m) => (
              <Chip key={m} label={MODE_INFO[m].label} selected={mode === m} onPress={() => setMode(m)} disabled={live} />
            ))}
          </ScrollView>

          {reflection ? (
            <View style={styles.banner} accessibilityLabel={`Talking about ${reflection.title}`}>
              <View style={styles.bannerText}>
                <Caption style={styles.bannerLabel}>{reflection.label} · today’s topic</Caption>
                <Body>{reflection.title}</Body>
              </View>
              <Pressable onPress={dismissReflection} accessibilityRole="button" accessibilityLabel="Remove reflection context" style={styles.bannerClose} disabled={live}>
                <Caption>✕</Caption>
              </Pressable>
            </View>
          ) : null}

          <View style={styles.orbWrap}>
            <Orb status={state.status} size={200} />
          </View>
          <Heading center style={styles.status}>
            {STATUS_LABELS[state.status]}
          </Heading>
          <Caption center style={styles.hint}>
            {live ? MODE_INFO[mode].hint : "Jedar listens only while a conversation is running."}
          </Caption>
          {state.error ? (
            <Caption center style={styles.error}>
              {state.error}
            </Caption>
          ) : null}

          <View style={styles.actions}>
            {!live ? (
              <Button title="Start talking" onPress={() => void start(selection)} disabled={!prefs.faith} />
            ) : (
              <Button title="End session" variant="danger" onPress={end} />
            )}
          </View>

          <View style={styles.transcript}>
            <TranscriptPanel entries={state.transcript} emptyHint="Your conversation will appear here. Nothing is saved unless you choose to." />
          </View>

          <View style={styles.composer}>
            <Composer onSend={(text) => sendText(text, selection)} disabled={state.status === "connecting"} />
          </View>

          {state.transcript.some((e) => e.final) && !live ? (
            <View style={styles.footerRow}>
              <Button title="Save conversation to journal" variant="secondary" onPress={saveConversation} compact />
              <Button title="Clear" variant="ghost" onPress={clear} compact />
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.huge },
  topRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: spacing.md },
  chips: { gap: spacing.sm, paddingVertical: spacing.xs },
  banner: { marginTop: spacing.lg, flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, borderRadius: radius.md, backgroundColor: colors.goldSoft, borderWidth: 1, borderColor: "rgba(216,181,112,0.35)" },
  bannerText: { flex: 1, gap: 2 },
  bannerLabel: { color: colors.gold },
  bannerClose: { padding: spacing.xs },
  orbWrap: { alignItems: "center", marginTop: spacing.sm, marginBottom: -spacing.lg },
  status: { color: colors.pearl },
  hint: { marginTop: spacing.xs, color: colors.textFaint },
  error: { marginTop: spacing.sm, color: colors.danger },
  actions: { marginTop: spacing.xl },
  transcript: { marginTop: spacing.xl },
  composer: { marginTop: spacing.md },
  footerRow: { marginTop: spacing.lg, gap: spacing.sm },
});
