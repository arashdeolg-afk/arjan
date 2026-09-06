import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Button } from "@/src/components/Button";
import { Card } from "@/src/components/Card";
import { FaithGlyph } from "@/src/components/FaithGlyph";
import { Body, Caption, Heading, Title } from "@/src/components/Typography";
import { FAITHS, FAITH_INFO, type Faith } from "@/src/lib/domain";
import { useApp } from "@/src/state/AppContext";
import { colors, spacing } from "@/src/theme/tokens";

export default function FaithSelection() {
  const router = useRouter();
  const { prefs, updatePrefs } = useApp();
  const [selected, setSelected] = useState<Faith | null>(prefs.faith);
  const [saving, setSaving] = useState(false);

  const next = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await updatePrefs({ faith: selected });
      router.push("/onboarding/voice");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen scroll>
      <Title style={styles.title}>Which faith should Jedar keep in mind?</Title>
      <Body muted style={styles.lead}>
        Jedar reflects with you in the language of your tradition. You can change this any time.
      </Body>
      <View style={styles.list}>
        {FAITHS.map((faith) => {
          const info = FAITH_INFO[faith];
          const isSelected = selected === faith;
          return (
            <Card key={faith} onPress={() => setSelected(faith)} selected={isSelected} style={styles.card} accessibilityLabel={`${info.label}. ${info.description}`}>
              <View style={styles.row}>
                <FaithGlyph faith={faith} selected={isSelected} />
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
      <Button title="Continue" onPress={next} disabled={!selected} loading={saving} style={styles.cta} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { marginTop: spacing.lg },
  lead: { marginTop: spacing.sm, marginBottom: spacing.xl },
  list: { gap: spacing.md },
  card: { padding: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.lg },
  text: { flex: 1, gap: 2 },
  indicator: { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center" },
  indicatorOn: { borderColor: colors.gold },
  indicatorDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.gold },
  cta: { marginTop: spacing.xxl },
});
