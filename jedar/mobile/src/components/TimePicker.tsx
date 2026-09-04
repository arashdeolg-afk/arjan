import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { TIME_PRESETS, formatReminderTime, parseTimeInput } from "@/src/lib/notifications";
import { Chip } from "./Chip";
import { Caption } from "./Typography";
import { colors, radius, spacing } from "@/src/theme/tokens";

type Props = { hour: number; minute: number; onChange: (hour: number, minute: number) => void; disabled?: boolean };

/** Dependency-free time picker: presets, hour/minute steppers, and a typed time. */
export function TimePicker({ hour, minute, onChange, disabled }: Props) {
  const [typed, setTyped] = useState("");
  const [typedError, setTypedError] = useState(false);

  const step = (h: number, m: number) => {
    const total = (((hour * 60 + minute + h * 60 + m) % 1440) + 1440) % 1440;
    onChange(Math.floor(total / 60), total % 60);
  };

  const applyTyped = () => {
    const parsed = parseTimeInput(typed);
    if (!parsed) {
      setTypedError(true);
      return;
    }
    setTypedError(false);
    setTyped("");
    onChange(parsed.hour, parsed.minute);
  };

  return (
    <View style={[styles.wrap, disabled && styles.disabled]} pointerEvents={disabled ? "none" : "auto"}>
      <View style={styles.presets}>
        {TIME_PRESETS.map((p) => (
          <Chip key={`${p.hour}:${p.minute}`} label={formatReminderTime(p.hour, p.minute)} selected={p.hour === hour && p.minute === minute} onPress={() => onChange(p.hour, p.minute)} tone="mint" />
        ))}
      </View>
      <View style={styles.stepperRow}>
        <Stepper label="Hour" onDown={() => step(-1, 0)} onUp={() => step(1, 0)} />
        <Text style={styles.time} accessibilityLabel={`Reminder time ${formatReminderTime(hour, minute)}`}>
          {formatReminderTime(hour, minute)}
        </Text>
        <Stepper label="Minute" onDown={() => step(0, -5)} onUp={() => step(0, 5)} />
      </View>
      <View style={styles.typedRow}>
        <TextInput
          value={typed}
          onChangeText={(t) => {
            setTyped(t);
            setTypedError(false);
          }}
          onSubmitEditing={applyTyped}
          placeholder="Type a time, e.g. 7:30 pm"
          placeholderTextColor={colors.textFaint}
          style={[styles.input, typedError && styles.inputError]}
          keyboardType="numbers-and-punctuation"
          returnKeyType="done"
          accessibilityLabel="Type a reminder time"
        />
        <Pressable onPress={applyTyped} style={styles.apply} accessibilityRole="button" accessibilityLabel="Apply typed time">
          <Text style={styles.applyText}>Set</Text>
        </Pressable>
      </View>
      {typedError ? <Caption style={styles.error}>Try a time like 7:30 or 19:30.</Caption> : null}
    </View>
  );
}

function Stepper({ label, onDown, onUp }: { label: string; onDown: () => void; onUp: () => void }) {
  return (
    <View style={styles.stepper}>
      <Pressable onPress={onUp} style={styles.stepBtn} accessibilityRole="button" accessibilityLabel={`${label} up`}>
        <Text style={styles.stepText}>+</Text>
      </Pressable>
      <Caption style={styles.stepLabel}>{label}</Caption>
      <Pressable onPress={onDown} style={styles.stepBtn} accessibilityRole="button" accessibilityLabel={`${label} down`}>
        <Text style={styles.stepText}>−</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.lg },
  disabled: { opacity: 0.45 },
  presets: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  stepperRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepper: { alignItems: "center", gap: 2 },
  stepBtn: { width: 40, height: 36, borderRadius: radius.sm, backgroundColor: colors.surfaceRaised, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  stepText: { color: colors.text, fontSize: 20, lineHeight: 22 },
  stepLabel: { color: colors.textFaint },
  time: { color: colors.pearl, fontSize: 32, fontWeight: "600", letterSpacing: 0.5, fontVariant: ["tabular-nums"] },
  typedRow: { flexDirection: "row", gap: spacing.sm },
  input: { flex: 1, height: 44, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, color: colors.text, paddingHorizontal: spacing.md },
  inputError: { borderColor: colors.danger },
  apply: { paddingHorizontal: spacing.lg, height: 44, borderRadius: radius.md, backgroundColor: colors.goldSoft, alignItems: "center", justifyContent: "center" },
  applyText: { color: colors.gold, fontWeight: "600" },
  error: { color: colors.danger },
});
