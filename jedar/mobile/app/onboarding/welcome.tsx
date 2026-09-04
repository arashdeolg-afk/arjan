import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Button } from "@/src/components/Button";
import { Orb } from "@/src/components/Orb";
import { Caption, Display, BodyLarge } from "@/src/components/Typography";
import { colors, spacing } from "@/src/theme/tokens";

export default function Welcome() {
  const router = useRouter();
  return (
    <Screen glow="center">
      <View style={styles.top}>
        <Orb status="idle" size={170} />
      </View>
      <View style={styles.middle}>
        <Display center>Jedar AI</Display>
        <BodyLarge center muted style={styles.subtitle}>
          Faith guidance by voice
        </BodyLarge>
      </View>
      <View style={styles.bottom}>
        <Button title="Begin" onPress={() => router.push("/onboarding/faith")} />
        <Caption center style={styles.boundary}>
          A supportive companion, never a religious authority
        </Caption>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { flex: 1.1, alignItems: "center", justifyContent: "flex-end" },
  middle: { flex: 0.8, justifyContent: "center", gap: spacing.sm },
  subtitle: { letterSpacing: 0.6 },
  bottom: { paddingBottom: spacing.huge, gap: spacing.lg },
  boundary: { color: colors.textFaint },
});
