import { useCallback, useState } from "react";
import { Alert, StyleSheet, TextInput, View } from "react-native";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Button } from "@/src/components/Button";
import { Body, BodyLarge, Caption, Title } from "@/src/components/Typography";
import { FAITH_INFO, JOURNAL_TYPE_INFO } from "@/src/lib/domain";
import { TITLE_MAX, type JournalEntry } from "@/src/lib/journal";
import { formatTimestamp } from "@/src/lib/dates";
import { useApp } from "@/src/state/AppContext";
import { colors, radius, spacing } from "@/src/theme/tokens";

export default function EntryScreen() {
  const router = useRouter();
  const { journal } = useApp();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [entry, setEntry] = useState<JournalEntry | null>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  useFocusEffect(
    useCallback(() => {
      if (!journal || typeof id !== "string") return;
      journal.get(id).then((e) => {
        setEntry(e);
        if (e) {
          setTitle(e.title);
          setBody(e.body);
        }
      });
    }, [journal, id]),
  );

  const save = async () => {
    if (!journal || !entry) return;
    setSaving(true);
    try {
      const updated = await journal.update(entry.id, { title, body });
      if (updated) setEntry(updated);
      setEditing(false);
    } catch (err) {
      Alert.alert("Could not save", err instanceof Error ? err.message : "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = () => {
    if (!journal || !entry) return;
    Alert.alert("Delete this entry?", "It will be removed from this device. This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          await journal.remove(entry.id);
          router.back();
        },
      },
    ]);
  };

  if (!entry) {
    return (
      <Screen>
        <Body muted center style={styles.missing}>
          This entry is no longer available.
        </Body>
        <Button title="Back" variant="secondary" onPress={() => router.back()} />
      </Screen>
    );
  }

  return (
    <Screen scroll glow="none">
      <View style={styles.meta}>
        <Caption style={styles.type}>{JOURNAL_TYPE_INFO[entry.type].label}</Caption>
        <Caption>{FAITH_INFO[entry.faith].label}</Caption>
      </View>
      {editing ? (
        <>
          <TextInput value={title} onChangeText={setTitle} style={styles.titleInput} maxLength={TITLE_MAX} accessibilityLabel="Title" />
          <TextInput value={body} onChangeText={setBody} style={styles.bodyInput} multiline textAlignVertical="top" accessibilityLabel="Body" />
          <View style={styles.actions}>
            <Button title="Save changes" onPress={save} loading={saving} disabled={!title.trim() || !body.trim()} />
            <Button
              title="Cancel"
              variant="ghost"
              onPress={() => {
                setTitle(entry.title);
                setBody(entry.body);
                setEditing(false);
              }}
            />
          </View>
        </>
      ) : (
        <>
          <Title>{entry.title}</Title>
          <BodyLarge style={styles.body} selectable>
            {entry.body}
          </BodyLarge>
          <View style={styles.timestamps}>
            <Caption>Created {formatTimestamp(entry.createdAt)}</Caption>
            {entry.updatedAt !== entry.createdAt ? <Caption>Updated {formatTimestamp(entry.updatedAt)}</Caption> : null}
          </View>
          <View style={styles.actions}>
            <Button title="Edit" variant="secondary" onPress={() => setEditing(true)} />
            <Button title="Delete" variant="danger" onPress={confirmDelete} />
            <Button title="Back" variant="ghost" onPress={() => router.back()} />
          </View>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  missing: { marginTop: spacing.huge, marginBottom: spacing.xl },
  meta: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.sm, marginBottom: spacing.lg },
  type: { color: colors.lavender },
  body: { marginTop: spacing.lg, color: colors.pearl },
  timestamps: { marginTop: spacing.xl, gap: 2 },
  titleInput: { color: colors.text, fontSize: 22, fontWeight: "600", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: spacing.md, marginBottom: spacing.lg },
  bodyInput: { minHeight: 220, color: colors.text, fontSize: 17, lineHeight: 26, padding: spacing.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  actions: { marginTop: spacing.xl, gap: spacing.sm },
});
