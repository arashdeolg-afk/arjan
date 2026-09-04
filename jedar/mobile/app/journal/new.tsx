import { useState } from "react";
import { Alert, StyleSheet, TextInput, View } from "react-native";
import { useRouter } from "expo-router";
import { Screen } from "@/src/components/Screen";
import { Button } from "@/src/components/Button";
import { Caption, Title } from "@/src/components/Typography";
import { TITLE_MAX } from "@/src/lib/journal";
import { FAITH_INFO } from "@/src/lib/domain";
import { useApp } from "@/src/state/AppContext";
import { colors, radius, spacing } from "@/src/theme/tokens";

export default function NewEntry() {
  const router = useRouter();
  const { journal, prefs } = useApp();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!journal || !prefs.faith) return;
    setSaving(true);
    try {
      await journal.create({ type: "note", title, body, faith: prefs.faith });
      router.back();
    } catch (err) {
      Alert.alert("Could not save", err instanceof Error ? err.message : "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Screen scroll glow="none">
      <Title style={styles.title}>New note</Title>
      <Caption style={styles.meta}>{prefs.faith ? FAITH_INFO[prefs.faith].label : ""} · stays on this device</Caption>
      <TextInput value={title} onChangeText={setTitle} placeholder="Title" placeholderTextColor={colors.textFaint} style={styles.titleInput} maxLength={TITLE_MAX} accessibilityLabel="Title" />
      <TextInput
        value={body}
        onChangeText={setBody}
        placeholder="What is on your heart today?"
        placeholderTextColor={colors.textFaint}
        style={styles.bodyInput}
        multiline
        textAlignVertical="top"
        accessibilityLabel="Note"
      />
      <View style={styles.actions}>
        <Button title="Save note" onPress={save} loading={saving} disabled={!title.trim() || !body.trim()} />
        <Button title="Cancel" variant="ghost" onPress={() => router.back()} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { marginTop: spacing.sm },
  meta: { marginTop: spacing.xs, marginBottom: spacing.xl, color: colors.textFaint },
  titleInput: { color: colors.text, fontSize: 20, fontWeight: "600", borderBottomWidth: 1, borderBottomColor: colors.border, paddingVertical: spacing.md, marginBottom: spacing.lg },
  bodyInput: { minHeight: 220, color: colors.text, fontSize: 17, lineHeight: 26, padding: spacing.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  actions: { marginTop: spacing.xl, gap: spacing.sm },
});
