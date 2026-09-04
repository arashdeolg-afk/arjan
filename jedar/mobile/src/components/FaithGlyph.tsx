import { StyleSheet, View } from "react-native";
import type { Faith } from "@/src/lib/domain";
import { colors } from "@/src/theme/tokens";

/**
 * Abstract, respectful marks: one soft geometric form per faith, built from
 * plain shapes rather than sacred symbols, text, or imagery.
 */
export function FaithGlyph({ faith, size = 44, selected }: { faith: Faith; size?: number; selected?: boolean }) {
  const tint = selected ? colors.gold : colors.mint;
  const s = size;
  return (
    <View style={[styles.wrap, { width: s, height: s, borderRadius: s / 2, borderColor: selected ? "rgba(216,181,112,0.5)" : colors.border }]}>
      {faith === "sikh" ? (
        // Two nested rings: unity and equality.
        <>
          <View style={[styles.ring, { width: s * 0.58, height: s * 0.58, borderColor: tint }]} />
          <View style={[styles.ring, { width: s * 0.3, height: s * 0.3, borderColor: tint }]} />
        </>
      ) : null}
      {faith === "muslim" ? (
        // A soft arch: shelter and mercy.
        <View style={[styles.arch, { width: s * 0.5, height: s * 0.5, borderColor: tint, borderTopLeftRadius: s * 0.25, borderTopRightRadius: s * 0.25 }]} />
      ) : null}
      {faith === "christian" ? (
        // Two gentle strokes meeting: love and grace.
        <>
          <View style={[styles.bar, { width: s * 0.12, height: s * 0.56, backgroundColor: tint, borderRadius: s * 0.06 }]} />
          <View style={[styles.bar, { width: s * 0.4, height: s * 0.12, backgroundColor: tint, borderRadius: s * 0.06, top: s * 0.33 }]} />
        </>
      ) : null}
      {faith === "hindu" ? (
        // A radiant point: devotion and inner light.
        <>
          <View style={[styles.dot, { width: s * 0.22, height: s * 0.22, backgroundColor: tint }]} />
          <View style={[styles.ring, { width: s * 0.6, height: s * 0.6, borderColor: tint, opacity: 0.6, borderStyle: "dashed" }]} />
        </>
      ) : null}
      {faith === "jewish" ? (
        // Overlapping soft squares: community and repair.
        <>
          <View style={[styles.square, { width: s * 0.34, height: s * 0.34, borderColor: tint, transform: [{ rotate: "45deg" }] }]} />
          <View style={[styles.square, { width: s * 0.34, height: s * 0.34, borderColor: tint, opacity: 0.7 }]} />
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center", borderWidth: 1, backgroundColor: colors.surfaceRaised },
  ring: { position: "absolute", borderWidth: 2, borderRadius: 999 },
  arch: { borderWidth: 2, borderBottomWidth: 0, marginTop: 4 },
  bar: { position: "absolute" },
  dot: { borderRadius: 999 },
  square: { position: "absolute", borderWidth: 2, borderRadius: 4 },
});
