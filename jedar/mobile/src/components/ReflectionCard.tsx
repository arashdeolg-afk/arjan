import { StyleSheet, View } from "react-native";
import type { PublicReflection } from "@/src/lib/domain";
import { FAITH_INFO } from "@/src/lib/domain";
import { Card } from "./Card";
import { Button } from "./Button";
import { Body, BodyLarge, Caption, Heading, Label } from "./Typography";
import { colors, spacing } from "@/src/theme/tokens";

type Props = { reflection: PublicReflection; onTalk: () => void; onSave: () => void; saved: boolean; saving?: boolean };

export function ReflectionCard({ reflection, onTalk, onSave, saved, saving }: Props) {
  const isScripture = reflection.label === "Scripture";
  return (
    <Card accent style={styles.card}>
      <View style={styles.header}>
        <Label>{reflection.label}</Label>
        <Caption>{FAITH_INFO[reflection.faith].label}</Caption>
      </View>
      <Heading style={styles.title}>{reflection.title}</Heading>
      <BodyLarge style={styles.body}>{reflection.body}</BodyLarge>
      {isScripture && reflection.sourceName && reflection.reference ? (
        <Body muted style={styles.source}>
          {reflection.sourceName}, {reflection.reference}
        </Body>
      ) : null}
      {!isScripture ? <Caption style={styles.note}>An original reflection written for Jedar, not scripture.</Caption> : null}
      <View style={styles.actions}>
        <Button title="Talk about this" onPress={onTalk} />
        <Button title={saved ? "Saved to journal" : "Save to journal"} variant="secondary" onPress={onSave} disabled={saved} loading={saving ?? false} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.sm },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.xs },
  title: { marginTop: spacing.xs },
  body: { marginTop: spacing.xs, color: colors.pearl },
  source: { marginTop: spacing.xs, fontStyle: "italic" },
  note: { marginTop: spacing.sm, color: colors.textFaint },
  actions: { marginTop: spacing.lg, gap: spacing.md },
});
