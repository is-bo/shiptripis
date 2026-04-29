import 'package:flutter/material.dart';

/// ShipTrip design tokens — "Mediterranean transit" aesthetic.
/// Algerian heritage emerald, Saharan ochre, parchment, gold.
class AppColors {
  AppColors._();

  static const parchment = Color(0xFFF4EFE6);
  static const parchmentDeep = Color(0xFFEAE3D2);
  static const parchmentSoft = Color(0xFFFAF6EE);

  static const ink = Color(0xFF0E1F2C);
  static const inkSoft = Color(0xFF2A3B49);
  static const inkMute = Color(0xFF6B7785);

  static const emerald = Color(0xFF0E5A4F);
  static const emeraldDeep = Color(0xFF073C34);
  static const emeraldGlow = Color(0xFF2A8475);

  static const terracotta = Color(0xFFE8763A);
  static const terracottaDeep = Color(0xFFC75E26);

  static const gold = Color(0xFFC9A961);
  static const goldDeep = Color(0xFFA88842);

  static const success = Color(0xFF2A8475);
  static const danger = Color(0xFFB23A2E);
  static const warning = Color(0xFFE8A33A);

  static const stamp = Color(0xFFB23A2E);

  static const hairline = Color(0x1A0E1F2C);
  static const hairlineSoft = Color(0x0D0E1F2C);
}

class AppRadius {
  AppRadius._();
  static const xs = 6.0;
  static const sm = 10.0;
  static const md = 16.0;
  static const lg = 24.0;
  static const xl = 32.0;
  static const pill = 999.0;
}

class AppSpacing {
  AppSpacing._();
  static const x1 = 4.0;
  static const x2 = 8.0;
  static const x3 = 12.0;
  static const x4 = 16.0;
  static const x5 = 20.0;
  static const x6 = 24.0;
  static const x8 = 32.0;
  static const x10 = 40.0;
  static const x12 = 48.0;
  static const x16 = 64.0;
  static const x20 = 80.0;
}

class AppShadows {
  AppShadows._();

  static const card = [
    BoxShadow(
      color: Color(0x0F0E1F2C),
      blurRadius: 24,
      offset: Offset(0, 8),
    ),
    BoxShadow(
      color: Color(0x080E1F2C),
      blurRadius: 4,
      offset: Offset(0, 2),
    ),
  ];

  static const elevated = [
    BoxShadow(
      color: Color(0x1A0E1F2C),
      blurRadius: 40,
      offset: Offset(0, 16),
    ),
    BoxShadow(
      color: Color(0x0F0E1F2C),
      blurRadius: 8,
      offset: Offset(0, 4),
    ),
  ];

  static const stamped = [
    BoxShadow(
      color: Color(0x14B23A2E),
      blurRadius: 0,
      offset: Offset(2, 2),
    ),
  ];
}

class AppDurations {
  AppDurations._();
  static const fast = Duration(milliseconds: 180);
  static const med = Duration(milliseconds: 320);
  static const slow = Duration(milliseconds: 540);
  static const epic = Duration(milliseconds: 900);
}

const kAppCurve = Cubic(0.16, 1, 0.3, 1); // expressive ease-out
