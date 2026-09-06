import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Button } from "@/src/components/Button";
import { Card } from "@/src/components/Card";
import { Body, Caption, Heading, Title } from "@/src/components/Typography";
import { JEDAR_VOICES, VOICE_INFO, type JedarVoice } from "@/src/lib/domain";
import { useApp } from "@/src/state/AppContext";
import { colors, spacing } from "@/src/theme/tokens";

const TONES: Record<JedarVoice, string> = { maya: colors.mint, noor: colors.lavender, ayaan: colors.gold };

export default function VoiceSelection() {
  const router = useRouter();
  const { prefs, updatePrefs } = useApp();
  const [selected, setSelected] = useState<JedarVoice>(prefs.voice);
  const [saving, setSaving] = useState(false);

  const finish = async () => {
    setSaving(true);
    try {
      await updatePrefs({ voice: selected, onboardingComplete: true });
      router.replace("/(tabs)/today");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen scroll>
      <Title style={styles.title}>Choose Jedar’s voice</Title>
      <Body muted style={styles.lead}>
        Pick the voice that feels easiest to sit with. You can change it in Settings.
      </Body>
      <View style={styles.list}>
        {JEDAR_VOICES.map((voice) => {
          const info = VOICE_INFO[voice];
          const isSelected = selected === voice;
          return (
            <Card key={voice} onPress={() => setSelected(voice)} selected={isSelected} style={styles.card} accessibilityLabel={`${info.label}, ${info.description}`}>
              <View style={styles.row}>
                <View style={[styles.swatch, { backgroundColor: TONES[voice], opacity: isSelected ? 1 : 0.55 }]} />
                <View style={styles.text}>
                  <Heading>{info.label}</Heading>
                  <Caption>{info.description}</Caption>
                </View>
                <View style={[styles.indicator, isSelected && styles.indicatorOn]}>{isSelected ? <View style={styles.indicatorDot} /> : null}</View>
              </View>
            </Card>
          );
        })}
      </View>
      <Button title="Finish" onPress={finish} loading={saving} style={styles.cta} />
      <Caption center style={styles.note}>
        Voice conversations need a development build; see Settings for details.
      </Caption>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { marginTop: spacing.lg },
  lead: { marginTop: spacing.sm, marginBottom: spacing.xl },
  list: { gap: spacing.md },
  card: { padding: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  swatch: { width: 40, height: 40, borderRadius: 20 },
  text: { flex: 1, gap: 2 },
  indicator: { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center" },
  indicatorOn: { borderColor: colors.gold },
  indicatorDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.gold },
  cta: { marginTop: spacing.xxl },
  note: { marginTop: spacing.lg, color: colors.textFaint },
});
