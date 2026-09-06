import { Redirect } from "expo-router";
import { useApp } from "@/src/state/AppContext";

export default function Index() {
  const { prefs } = useApp();
  return <Redirect href={prefs.onboardingComplete && prefs.faith ? "/(tabs)/today" : "/onboarding/welcome"} />;
}
