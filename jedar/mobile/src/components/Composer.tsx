import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { colors, radius, spacing } from "@/src/theme/tokens";

type Props = { onSend: (text: string) => Promise<void> | void; disabled?: boolean; placeholder?: string };

/** Text fallback for when speaking aloud is not possible. */
export function Composer({ onSend, disabled, placeholder = "Or type to Jedar…" }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const canSend = !disabled && !busy && text.trim().length > 0;

  const submit = async () => {
    if (!canSend) return;
    const value = text.trim();
    setText("");
    setBusy(true);
    try {
      await onSend(value);
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.row}>
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        placeholderTextColor={colors.textFaint}
        style={styles.input}
        multiline
        maxLength={2000}
        editable={!disabled && !busy}
        returnKeyType="send"
        blurOnSubmit
        onSubmitEditing={submit}
        accessibilityLabel="Message to Jedar"
      />
      <Pressable onPress={submit} disabled={!canSend} accessibilityRole="button" accessibilityLabel="Send" style={({ pressed }) => [styles.send, !canSend && styles.sendDisabled, pressed && styles.pressed]}>
        <Text style={styles.sendText}>{busy ? "…" : "Send"}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm },
  input: {
    flex: 1,
    minHeight: 48,
    maxHeight: 120,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    color: colors.text,
    fontSize: 16,
  },
  send: { height: 48, paddingHorizontal: spacing.lg, borderRadius: radius.pill, backgroundColor: colors.goldSoft, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "rgba(216,181,112,0.4)" },
  sendDisabled: { opacity: 0.4 },
  pressed: { opacity: 0.8 },
  sendText: { color: colors.gold, fontWeight: "600", fontSize: 15 },
});
