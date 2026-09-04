import { Text, type TextProps, StyleSheet } from "react-native";
import { colors, type } from "@/src/theme/tokens";

type Props = TextProps & { muted?: boolean; color?: string; center?: boolean };

function make(style: object, defaultColor: string = colors.text) {
  return function Typo({ muted, color, center, style: extra, ...rest }: Props) {
    return (
      <Text
        {...rest}
        style={[style, { color: color ?? (muted ? colors.textMuted : defaultColor) }, center ? styles.center : null, extra]}
        maxFontSizeMultiplier={1.4}
      />
    );
  };
}

export const Display = make(type.display);
export const Title = make(type.title);
export const Heading = make(type.heading);
export const Body = make(type.body);
export const BodyLarge = make(type.bodyLarge);
export const Caption = make(type.caption, colors.textMuted);
export const Label = make(type.label, colors.gold);

const styles = StyleSheet.create({ center: { textAlign: "center" } });
