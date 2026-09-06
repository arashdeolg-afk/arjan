import { useEffect, useRef } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import type { TranscriptEntry } from "@/src/lib/realtimeEvents";
import { Body, Caption } from "./Typography";
import { colors, radius, spacing } from "@/src/theme/tokens";

export function TranscriptPanel({ entries, emptyHint }: { entries: TranscriptEntry[]; emptyHint: string }) {
  const ref = useRef<ScrollView>(null);
  useEffect(() => {
    const t = setTimeout(() => ref.current?.scrollToEnd({ animated: true }), 50);
    return () => clearTimeout(t);
  }, [entries]);
  return (
    <View style={styles.panel} accessibilityLabel="Live transcript">
      <ScrollView ref={ref} contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {entries.length === 0 ? (
          <Caption style={styles.empty}>{emptyHint}</Caption>
        ) : (
          entries.map((e) => (
            <View key={e.id} style={[styles.line, e.role === "user" ? styles.user : styles.assistant]}>
              <Caption style={styles.who}>{e.role === "user" ? "You" : "Jedar"}</Caption>
              <Body style={[styles.text, !e.final && styles.partial]}>{e.text || "…"}</Body>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { maxHeight: 220, minHeight: 90, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: "rgba(0,0,0,0.22)" },
  content: { padding: spacing.lg, gap: spacing.md },
  empty: { textAlign: "center", color: colors.textFaint, paddingVertical: spacing.md },
  line: { gap: 2 },
  user: { alignItems: "flex-end" },
  assistant: { alignItems: "flex-start" },
  who: { color: colors.textFaint },
  text: { color: colors.pearl, maxWidth: "92%" },
  partial: { opacity: 0.75 },
});
