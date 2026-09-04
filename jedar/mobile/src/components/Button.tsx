import { Pressable, StyleSheet, Text, View, ActivityIndicator, type ViewStyle } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { colors, gradients, radius, spacing } from "@/src/theme/tokens";

type Variant = "primary" | "secondary" | "ghost" | "danger";

type Props = {
  title: string;
  onPress?: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
  accessibilityHint?: string;
  compact?: boolean;
};

export function Button({ title, onPress, variant = "primary", disabled, loading, style, accessibilityHint, compact }: Props) {
  const inactive = disabled || loading;
  const content = (
    <View style={[styles.inner, compact && styles.innerCompact]}>
      {loading ? <ActivityIndicator color={variant === "primary" ? colors.charcoal : colors.text} /> : null}
      <Text
        style={[
          styles.text,
          variant === "primary" && styles.textPrimary,
          variant === "danger" && styles.textDanger,
          variant === "ghost" && styles.textGhost,
          compact && styles.textCompact,
        ]}
        maxFontSizeMultiplier={1.3}
      >
        {title}
      </Text>
    </View>
  );
  return (
    <Pressable
      onPress={onPress}
      disabled={inactive}
      accessibilityRole="button"
      accessibilityLabel={title}
      {...(accessibilityHint ? { accessibilityHint } : {})}
      accessibilityState={{ disabled: !!inactive }}
      style={({ pressed }) => [
        styles.base,
        variant === "secondary" && styles.secondary,
        variant === "ghost" && styles.ghost,
        variant === "danger" && styles.danger,
        compact && styles.compact,
        pressed && styles.pressed,
        inactive && styles.disabled,
        style,
      ]}
    >
      {variant === "primary" ? (
        <LinearGradient colors={[...gradients.primaryButton]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.gradient}>
          {content}
        </LinearGradient>
      ) : (
        content
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: { borderRadius: radius.pill, overflow: "hidden", minHeight: 54, justifyContent: "center" },
  compact: { minHeight: 42 },
  gradient: { flex: 1, justifyContent: "center", borderRadius: radius.pill },
  inner: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingHorizontal: spacing.xl, paddingVertical: spacing.md },
  innerCompact: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  secondary: { backgroundColor: colors.surfaceRaised, borderWidth: 1, borderColor: colors.borderStrong },
  ghost: { backgroundColor: "transparent" },
  danger: { backgroundColor: colors.dangerSoft, borderWidth: 1, borderColor: "rgba(224,138,138,0.35)" },
  pressed: { opacity: 0.85, transform: [{ scale: 0.99 }] },
  disabled: { opacity: 0.5 },
  text: { color: colors.text, fontSize: 17, fontWeight: "600", letterSpacing: 0.3 },
  textCompact: { fontSize: 15 },
  textPrimary: { color: colors.charcoal },
  textDanger: { color: colors.danger },
  textGhost: { color: colors.textMuted },
});
