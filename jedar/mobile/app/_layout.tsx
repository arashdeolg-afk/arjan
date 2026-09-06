import { useEffect } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Stack, useRouter } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { AppProvider, useApp } from "@/src/state/AppContext";
import { addNotificationTapListener, getColdStartRoute } from "@/src/lib/notificationService";
import { Body, Caption } from "@/src/components/Typography";
import { colors } from "@/src/theme/tokens";

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AppProvider>
        <Root />
      </AppProvider>
    </SafeAreaProvider>
  );
}

function Root() {
  const { ready, error, prefs } = useApp();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    const remove = addNotificationTapListener((route) => {
      if (prefs.onboardingComplete) router.navigate(route);
    });
    getColdStartRoute().then((route) => {
      if (route && prefs.onboardingComplete) router.navigate(route);
    });
    return remove;
  }, [ready, prefs.onboardingComplete, router]);

  if (error) {
    return (
      <View style={styles.center}>
        <Body center>Jedar could not open its local storage.</Body>
        <Caption center>{error}</Caption>
      </View>
    );
  }
  if (!ready) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.gold} />
      </View>
    );
  }
  return (
    <Stack screenOptions={{ headerShown: false, animation: "fade", contentStyle: { backgroundColor: colors.charcoal } }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="onboarding/welcome" />
      <Stack.Screen name="onboarding/faith" />
      <Stack.Screen name="onboarding/voice" />
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="journal/new" options={{ presentation: "modal" }} />
      <Stack.Screen name="journal/[id]" />
    </Stack>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, backgroundColor: colors.charcoal, alignItems: "center", justifyContent: "center", padding: 32, gap: 8 },
});
