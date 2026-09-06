import { Pressable, StyleSheet, Text } from "react-native";
import { colors, radius, spacing } from "@/src/theme/tokens";

type Props = { label: string; selected?: boolean; onPress?: () => void; tone?: "gold" | "mint" | "lavender"; disabled?: boolean };

const TONES = {
  gold: { bg: colors.goldSoft, fg: colors.gold, border: "rgba(216,181,112,0.5)" },
  mint: { bg: colors.mintSoft, fg: colors.mint, border: "rgba(168,228,204,0.5)" },
  lavender: { bg: colors.lavenderSoft, fg: colors.lavender, border: "rgba(199,184,242,0.5)" },
};

export function Chip({ label, selected, onPress, tone = "gold", disabled }: Props) {
  const t = TONES[tone];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected, disabled: !!disabled }}
      style={({ pressed }) => [
        styles.chip,
        selected && { backgroundColor: t.bg, borderColor: t.border },
        pressed && styles.pressed,
        disabled && styles.disabled,
      ]}
    >
      <Text style={[styles.text, selected && { color: t.fg }]} maxFontSizeMultiplier={1.3}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  pressed: { opacity: 0.8 },
  disabled: { opacity: 0.5 },
  text: { color: colors.textMuted, fontSize: 14, fontWeight: "600", letterSpacing: 0.3 },
});
