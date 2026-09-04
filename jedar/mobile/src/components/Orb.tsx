import { useEffect, useRef } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import type { VoiceStatus } from "@/src/lib/realtimeEvents";
import { colors, gradients } from "@/src/theme/tokens";

type Props = { status: VoiceStatus; size?: number };

/**
 * Jedar's orb: a warm pearl-and-gold core wrapped in soft mint and lavender
 * light. It breathes slowly while idle, swells and shimmers while speaking,
 * sends out a listening halo, and turns inward (slow drift, dimmer) while
 * reflecting. Built from gradients and plain shapes; no image assets.
 */
export function Orb({ status, size = 220 }: Props) {
  const breath = useRef(new Animated.Value(0)).current;
  const halo = useRef(new Animated.Value(0)).current;
  const drift = useRef(new Animated.Value(0)).current;
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    breath.stopAnimation();
    halo.stopAnimation();
    shimmer.stopAnimation();

    const speaking = status === "speaking";
    const breathing = Animated.loop(
      Animated.sequence([
        Animated.timing(breath, { toValue: 1, duration: speaking ? 900 : status === "reflecting" ? 4200 : 3200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
        Animated.timing(breath, { toValue: 0, duration: speaking ? 900 : status === "reflecting" ? 4200 : 3200, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      ]),
    );
    breathing.start();

    let haloLoop: Animated.CompositeAnimation | null = null;
    if (status === "listening" || status === "connecting") {
      halo.setValue(0);
      haloLoop = Animated.loop(Animated.timing(halo, { toValue: 1, duration: status === "connecting" ? 1400 : 2400, easing: Easing.out(Easing.quad), useNativeDriver: true }));
      haloLoop.start();
    } else {
      halo.setValue(0);
    }

    let shimmerLoop: Animated.CompositeAnimation | null = null;
    if (speaking) {
      shimmerLoop = Animated.loop(
        Animated.sequence([
          Animated.timing(shimmer, { toValue: 1, duration: 420, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
          Animated.timing(shimmer, { toValue: 0, duration: 560, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        ]),
      );
      shimmerLoop.start();
    } else {
      Animated.timing(shimmer, { toValue: 0, duration: 400, useNativeDriver: true }).start();
    }

    return () => {
      breathing.stop();
      haloLoop?.stop();
      shimmerLoop?.stop();
    };
  }, [status, breath, halo, shimmer]);

  useEffect(() => {
    const loop = Animated.loop(Animated.timing(drift, { toValue: 1, duration: 26000, easing: Easing.linear, useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [drift]);

  const speaking = status === "speaking";
  const reflecting = status === "reflecting";
  const paused = status === "paused";

  const coreScale = breath.interpolate({ inputRange: [0, 1], outputRange: [1, speaking ? 1.12 : 1.05] });
  const glowScale = breath.interpolate({ inputRange: [0, 1], outputRange: [1, speaking ? 1.2 : 1.08] });
  const glowOpacity = breath.interpolate({ inputRange: [0, 1], outputRange: [reflecting ? 0.45 : 0.65, reflecting ? 0.6 : speaking ? 1 : 0.85] });
  const haloScale = halo.interpolate({ inputRange: [0, 1], outputRange: [1, 1.5] });
  const haloOpacity = halo.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 0.45, 0] });
  const rotate = drift.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "360deg"] });
  const shimmerOpacity = shimmer.interpolate({ inputRange: [0, 1], outputRange: [0, 0.55] });

  const s = size;
  return (
    <View style={[styles.wrap, { width: s * 1.7, height: s * 1.7 }]} accessible accessibilityRole="image" accessibilityLabel={`Jedar orb, ${status}`}>
      {/* Listening halo */}
      <Animated.View style={[styles.halo, { width: s * 1.15, height: s * 1.15, borderRadius: s, opacity: haloOpacity, transform: [{ scale: haloScale }] }]} />

      {/* Ambient light: lavender and mint, slowly drifting */}
      <Animated.View style={[styles.abs, { width: s * 1.6, height: s * 1.6, opacity: glowOpacity, transform: [{ scale: glowScale }, { rotate }] }]}>
        <LinearGradient colors={[...gradients.orbLavender]} start={{ x: 0.2, y: 0.1 }} end={{ x: 0.8, y: 0.9 }} style={[styles.round, { borderRadius: s }]} />
        <LinearGradient colors={[...gradients.orbMint]} start={{ x: 0.9, y: 0.8 }} end={{ x: 0.1, y: 0.2 }} style={[styles.round, StyleSheet.absoluteFill, { borderRadius: s }]} />
      </Animated.View>

      {/* Core */}
      <Animated.View style={[styles.core, { width: s, height: s, borderRadius: s / 2, opacity: paused ? 0.55 : 1, transform: [{ scale: coreScale }] }]}>
        <LinearGradient colors={[...gradients.orbCore]} start={{ x: 0.25, y: 0.15 }} end={{ x: 0.85, y: 0.95 }} style={[styles.round, { borderRadius: s / 2 }]} />
        <View style={[styles.innerLight, { width: s * 0.55, height: s * 0.55, borderRadius: s * 0.3, top: s * 0.12, left: s * 0.16 }]} />
        <View style={[styles.innerShade, { width: s * 0.9, height: s * 0.9, borderRadius: s * 0.45, top: s * 0.22, left: s * 0.08 }]} />
        <Animated.View style={[styles.shimmer, { borderRadius: s / 2, opacity: shimmerOpacity }]} />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", justifyContent: "center" },
  abs: { position: "absolute" },
  round: { flex: 1 },
  halo: { position: "absolute", borderWidth: 1.5, borderColor: colors.mint },
  core: {
    overflow: "hidden",
    shadowColor: colors.gold,
    shadowOpacity: 0.45,
    shadowRadius: 40,
    shadowOffset: { width: 0, height: 0 },
    elevation: 12,
  },
  innerLight: { position: "absolute", backgroundColor: "rgba(255,255,255,0.35)" },
  innerShade: { position: "absolute", backgroundColor: "rgba(120,90,40,0.16)" },
  shimmer: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(168,228,204,0.6)" },
});
