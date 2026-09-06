import { StyleSheet, View } from "react-native";
import { colors } from "@/src/theme/tokens";

export type TabName = "today" | "voice" | "journal" | "settings";

/** Small original glyphs for the tab bar, drawn from plain shapes. */
export function TabGlyph({ name, focused }: { name: TabName; focused: boolean }) {
  const c = focused ? colors.gold : colors.textFaint;
  switch (name) {
    case "today":
      return (
        <View style={styles.box}>
          <View style={[styles.ring, { borderColor: c }]} />
          <View style={[styles.dot, { backgroundColor: c }]} />
        </View>
      );
    case "voice":
      return (
        <View style={styles.box}>
          <View style={[styles.orb, { backgroundColor: c, opacity: focused ? 1 : 0.7 }]} />
          <View style={[styles.halo, { borderColor: c }]} />
        </View>
      );
    case "journal":
      return (
        <View style={styles.box}>
          <View style={[styles.line, { backgroundColor: c, width: 18, top: 5 }]} />
          <View style={[styles.line, { backgroundColor: c, width: 18, top: 11 }]} />
          <View style={[styles.line, { backgroundColor: c, width: 11, top: 17 }]} />
        </View>
      );
    case "settings":
      return (
        <View style={styles.box}>
          <View style={[styles.ring, { borderColor: c, width: 18, height: 18 }]} />
          <View style={[styles.ring, { borderColor: c, width: 8, height: 8, borderWidth: 2 }]} />
        </View>
      );
  }
}

const styles = StyleSheet.create({
  box: { width: 24, height: 24, alignItems: "center", justifyContent: "center" },
  ring: { position: "absolute", width: 20, height: 20, borderRadius: 999, borderWidth: 1.5 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  orb: { width: 12, height: 12, borderRadius: 6 },
  halo: { position: "absolute", width: 22, height: 22, borderRadius: 999, borderWidth: 1, opacity: 0.5 },
  line: { position: "absolute", height: 2, borderRadius: 1, left: 3 },
});
