/**
 * One design system for both clients.
 *
 * Deep ocean navy ground, seafoam accent, light type. Cards are translucent
 * white over the navy rather than solid fills, which is what gives the
 * glassmorphism; on web they also get a real backdrop blur (see `glass`).
 *
 * Both apps import from here so a palette change lands in one place instead
 * of being retyped across five screens.
 */

import { Platform, type TextStyle, type ViewStyle } from 'react-native';

export const colors = {
  /** Deep ocean navy. The ground everything sits on. */
  background: '#0B132B',
  /** A half-step up from the ground, for panels that need separating. */
  backgroundElevated: '#101A38',
  /** Translucent white fills -- the glassmorphism layers. */
  glassFill: 'rgba(255, 255, 255, 0.06)',
  glassFillStrong: 'rgba(255, 255, 255, 0.10)',
  border: 'rgba(255, 255, 255, 0.12)',
  borderStrong: 'rgba(255, 255, 255, 0.22)',

  /** Crisp seafoam. Active indicators and primary actions only. */
  accent: '#48CAE4',
  accentSoft: 'rgba(72, 202, 228, 0.14)',
  /** Type that sits *on* a seafoam fill. */
  onAccent: '#06182E',

  text: '#F4F7FB',
  textMuted: '#A9B4C6',
  textFaint: '#7B869A',

  danger: '#FF6B6B',
  warning: '#FFC043',
  success: '#5BD99A',
} as const;

/** 12px on cards, per the design spec. */
export const radius = {
  sm: 8,
  card: 12,
  lg: 16,
  pill: 999,
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

/**
 * Sharp, geometric sans. On web this is a stack of geometric faces with a
 * system fallback; native falls through to the platform font, which is already
 * geometric enough that shipping a custom font file is not worth the weight.
 */
export const fontFamily = Platform.select({
  web: 'Inter, "SF Pro Display", "Helvetica Neue", Arial, sans-serif',
  default: undefined,
});

/** Tight tracking on headings is most of what reads as "geometric". */
export const type = {
  display: { fontFamily, fontSize: 26, fontWeight: '800', letterSpacing: -0.6 },
  title: { fontFamily, fontSize: 21, fontWeight: '700', letterSpacing: -0.4 },
  heading: { fontFamily, fontSize: 17, fontWeight: '700', letterSpacing: -0.2 },
  body: { fontFamily, fontSize: 15, fontWeight: '400' },
  label: { fontFamily, fontSize: 14, fontWeight: '600' },
  meta: { fontFamily, fontSize: 13, fontWeight: '400' },
  /** Section headers: uppercase, widely tracked. */
  eyebrow: {
    fontFamily,
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1.1,
    textTransform: 'uppercase',
  },
  // `as const` keeps fontWeight as the literal "800" rather than widening to
  // string, which TextStyle rejects.
} as const satisfies Record<string, TextStyle>;

/** Soft drop shadow for floating elements. */
export const shadow = {
  soft: Platform.select({
    web: { boxShadow: '0 8px 24px rgba(0, 0, 0, 0.35)' },
    default: {
      shadowColor: '#000',
      shadowOpacity: 0.35,
      shadowRadius: 16,
      shadowOffset: { width: 0, height: 8 },
      elevation: 8,
    },
  }) as ViewStyle,
} as const;

/**
 * A glass card: translucent fill, hairline border, 12px corners.
 *
 * `backdropFilter` is a web-only CSS property that react-native-web passes
 * through; it is what actually blurs what sits behind the card. Native has no
 * equivalent without `expo-blur`, so there it degrades to the plain
 * translucent fill, which still reads correctly.
 */
export const glass = {
  backgroundColor: colors.glassFill,
  borderWidth: 1,
  borderColor: colors.border,
  borderRadius: radius.card,
  ...(Platform.OS === 'web'
    ? ({ backdropFilter: 'blur(14px)' } as unknown as ViewStyle)
    : null),
} as ViewStyle;
