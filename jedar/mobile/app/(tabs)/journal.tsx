import { useCallback, useState } from "react";
import { FlatList, Pressable, StyleSheet, TextInput, View } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Chip } from "@/src/components/Chip";
import { Card } from "@/src/components/Card";
import { Body, Caption, Heading, Title } from "@/src/components/Typography";
import { FAITHS, FAITH_INFO, JOURNAL_TYPES, JOURNAL_TYPE_INFO, type Faith, type JournalEntryType } from "@/src/lib/domain";
import type { JournalEntry } from "@/src/lib/journal";
import { formatTimestamp } from "@/src/lib/dates";
import { useApp } from "@/src/state/AppContext";
import { colors, radius, spacing } from "@/src/theme/tokens";

export default function Journal() {
  const router = useRouter();
  const { journal } = useApp();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [faith, setFaith] = useState<Faith | undefined>(undefined);
  const [type, setType] = useState<JournalEntryType | undefined>(undefined);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    if (!journal) return;
    setEntries(await journal.list({ faith, type, query }));
  }, [journal, faith, type, query]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  return (
    <Screen padded={false}>
      <FlatList
        data={entries}
        keyExtractor={(e) => e.id}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.header}>
            <Title>Journal</Title>
            <Caption style={styles.privacy}>Kept only on this device.</Caption>
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search your entries"
              placeholderTextColor={colors.textFaint}
              style={styles.search}
              accessibilityLabel="Search journal"
              returnKeyType="search"
            />
            <View style={styles.chips}>
              <Chip label="All faiths" selected={!faith} onPress={() => setFaith(undefined)} tone="mint" />
              {FAITHS.map((f) => (
                <Chip key={f} label={FAITH_INFO[f].label} selected={faith === f} onPress={() => setFaith(faith === f ? undefined : f)} tone="mint" />
              ))}
            </View>
            <View style={styles.chips}>
              <Chip label="All types" selected={!type} onPress={() => setType(undefined)} tone="lavender" />
              {JOURNAL_TYPES.map((t) => (
                <Chip key={t} label={JOURNAL_TYPE_INFO[t].label} selected={type === t} onPress={() => setType(type === t ? undefined : t)} tone="lavender" />
              ))}
            </View>
          </View>
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Body center muted>
              Nothing here yet. Save today’s reflection, write a note, or keep a conversation you found helpful.
            </Body>
          </View>
        }
        renderItem={({ item }) => (
          <Card onPress={() => router.push({ pathname: "/journal/[id]", params: { id: item.id } })} style={styles.card} accessibilityLabel={`${JOURNAL_TYPE_INFO[item.type].label}: ${item.title}`}>
            <View style={styles.cardTop}>
              <Caption style={styles.type}>{JOURNAL_TYPE_INFO[item.type].label}</Caption>
              <Caption>{FAITH_INFO[item.faith].label}</Caption>
            </View>
            <Heading numberOfLines={1}>{item.title}</Heading>
            <Body muted numberOfLines={2} style={styles.preview}>
              {item.body}
            </Body>
            <Caption style={styles.time}>{formatTimestamp(item.createdAt)}</Caption>
          </Card>
        )}
      />
      <Pressable onPress={() => router.push("/journal/new")} style={styles.fab} accessibilityRole="button" accessibilityLabel="New entry">
        <Caption style={styles.fabText}>＋ New entry</Caption>
      </Pressable>
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: { paddingHorizontal: spacing.xl, paddingBottom: 120, gap: spacing.md },
  header: { paddingTop: spacing.lg, gap: spacing.md, marginBottom: spacing.sm },
  privacy: { color: colors.textFaint, marginTop: -spacing.sm },
  search: { height: 46, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, color: colors.text, paddingHorizontal: spacing.lg },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  empty: { paddingVertical: spacing.huge, paddingHorizontal: spacing.lg },
  card: { padding: spacing.lg, gap: spacing.xs },
  cardTop: { flexDirection: "row", justifyContent: "space-between" },
  type: { color: colors.lavender },
  preview: { marginTop: 2 },
  time: { marginTop: spacing.sm, color: colors.textFaint },
  fab: { position: "absolute", right: spacing.xl, bottom: spacing.xl, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.pill, backgroundColor: colors.gold, shadowColor: colors.gold, shadowOpacity: 0.4, shadowRadius: 18, shadowOffset: { width: 0, height: 6 }, elevation: 6 },
  fabText: { color: colors.charcoal, fontWeight: "700" },
});
