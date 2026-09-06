import { type ReactNode } from "react";
import { Pressable, StyleSheet, View, type ViewStyle } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, gradients, radius, spacing } from "@/src/theme/tokens";

type Props = { children: ReactNode; style?: ViewStyle; onPress?: () => void; selected?: boolean; accent?: boolean; accessibilityLabel?: string };

/** Layered charcoal card with a hairline gold edge; mature and rounded, never glassy. */
export function Card({ children, style, onPress, selected, accent, accessibilityLabel }: Props) {
  const body = (
    <View style={[styles.card, selected && styles.selected, style]}>
      {accent ? <LinearGradient colors={[...gradients.cardEdge]} start={{ x: 0, y: 0 }} end={{ x: 0, y: 1 }} style={styles.edge} /> : null}
      {children}
    </View>
  );
  if (!onPress) return body;
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      {...(accessibilityLabel ? { accessibilityLabel } : {})}
      accessibilityState={{ selected: !!selected }}
      style={({ pressed }) => [pressed && styles.pressed]}
    >
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.xl,
    overflow: "hidden",
  },
  selected: { borderColor: "rgba(216,181,112,0.6)", backgroundColor: "rgba(216,181,112,0.07)" },
  edge: { position: "absolute", top: 0, left: 0, right: 0, height: 2 },
  pressed: { opacity: 0.9 },
});
