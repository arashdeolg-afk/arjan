import { type ReactNode } from "react";
import { StyleSheet, View, ScrollView, type ViewStyle } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { colors, gradients, spacing } from "@/src/theme/tokens";

type Props = {
  children: ReactNode;
  scroll?: boolean;
  padded?: boolean;
  style?: ViewStyle;
  contentStyle?: ViewStyle;
  /** Position of the soft atmospheric light. */
  glow?: "top" | "center" | "none";
};

/** Layered midnight gradient with soft emerald, gold and lavender light. */
export function Screen({ children, scroll = false, padded = true, style, contentStyle, glow = "top" }: Props) {
  const inner = padded ? [styles.padded, contentStyle] : [contentStyle];
  return (
    <View style={[styles.root, style]}>
      <StatusBar style="light" />
      <LinearGradient colors={[...gradients.screen]} locations={[0, 0.35, 0.7, 1]} style={StyleSheet.absoluteFill} />
      {glow !== "none" ? <Atmosphere position={glow} /> : null}
      <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
        {scroll ? (
          <ScrollView contentContainerStyle={[styles.scroll, ...inner]} keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}>
            {children}
          </ScrollView>
        ) : (
          <View style={[styles.fill, ...inner]}>{children}</View>
        )}
      </SafeAreaView>
    </View>
  );
}

function Atmosphere({ position }: { position: "top" | "center" }) {
  const top = position === "top";
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <View style={[styles.blob, { backgroundColor: colors.emerald, opacity: 0.22, top: top ? -120 : "25%", left: -80, width: 320, height: 320 }]} />
      <View style={[styles.blob, { backgroundColor: colors.lavender, opacity: 0.1, top: top ? 40 : "40%", right: -120, width: 300, height: 300 }]} />
      <View style={[styles.blob, { backgroundColor: colors.gold, opacity: 0.08, bottom: -140, left: "20%", width: 360, height: 360 }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.charcoal },
  safe: { flex: 1 },
  fill: { flex: 1 },
  scroll: { flexGrow: 1, paddingBottom: spacing.huge },
  padded: { paddingHorizontal: spacing.xl, paddingTop: spacing.lg },
  blob: { position: "absolute", borderRadius: 999, transform: [{ scale: 1.6 }] },
});
