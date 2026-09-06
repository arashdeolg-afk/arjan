import { Tabs } from "expo-router";
import { TabGlyph } from "@/src/components/TabGlyph";
import { colors } from "@/src/theme/tokens";

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.gold,
        tabBarInactiveTintColor: colors.textFaint,
        tabBarStyle: { backgroundColor: "#0C1019", borderTopColor: colors.border, height: 78, paddingTop: 8 },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600", letterSpacing: 0.4 },
        sceneStyle: { backgroundColor: colors.charcoal },
      }}
    >
      <Tabs.Screen name="today" options={{ title: "Today", tabBarIcon: ({ focused }) => <TabGlyph name="today" focused={focused} /> }} />
      <Tabs.Screen name="voice" options={{ title: "Voice", tabBarIcon: ({ focused }) => <TabGlyph name="voice" focused={focused} /> }} />
      <Tabs.Screen name="journal" options={{ title: "Journal", tabBarIcon: ({ focused }) => <TabGlyph name="journal" focused={focused} /> }} />
      <Tabs.Screen name="settings" options={{ title: "Settings", tabBarIcon: ({ focused }) => <TabGlyph name="settings" focused={focused} /> }} />
    </Tabs>
  );
}
