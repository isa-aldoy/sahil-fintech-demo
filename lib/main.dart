import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api.dart';
import 'screens.dart';
import 'strings.dart';

void main() => runApp(SahilApp(api: Api()));

const ink = Color(0xFF10212B);
const tide = Color(0xFF0F5C5E);
const coral = Color(0xFFE8603C);
const sand = Color(0xFFF7F3EC);

ThemeData sahilTheme(Brightness b) {
  final dark = b == Brightness.dark;
  final scheme = ColorScheme.fromSeed(seedColor: tide, brightness: b).copyWith(
    primary: dark ? const Color(0xFF6FD6CF) : tide,
    secondary: coral,
    surface: dark ? const Color(0xFF0C1820) : sand,
    surfaceContainerHighest: dark ? const Color(0xFF172832) : Colors.white,
  );
  return ThemeData(
    useMaterial3: true,
    fontFamily: 'Plex', // bundled (OFL): covers Arabic and Latin, works offline
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    appBarTheme: AppBarTheme(backgroundColor: scheme.surface, surfaceTintColor: Colors.transparent, centerTitle: false),
    cardTheme: CardThemeData(
      elevation: 0,
      color: scheme.surfaceContainerHighest,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size.fromHeight(54),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: scheme.surfaceContainerHighest,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: scheme.surfaceContainerHighest,
      indicatorColor: scheme.primary.withAlpha(36),
      height: 68,
    ),
  );
}

class SahilApp extends StatefulWidget {
  const SahilApp({super.key, required this.api});
  final Api api;
  @override
  State<SahilApp> createState() => _SahilAppState();
}

class _SahilAppState extends State<SahilApp> {
  @override
  void initState() {
    super.initState();
    widget.api.onSignedOut = () {
      if (mounted) setState(() {});
    };
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: Listenable.merge([appLocale, appDark]),
      builder: (context, _) => MaterialApp(
        title: 'Sahil',
        debugShowCheckedModeBanner: false,
        locale: appLocale.value,
        supportedLocales: const [Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: sahilTheme(Brightness.light),
        darkTheme: sahilTheme(Brightness.dark),
        themeMode: appDark.value ? ThemeMode.dark : ThemeMode.light,
        home: AnimatedSwitcher(
          duration: const Duration(milliseconds: 350),
          child: widget.api.signedIn
              ? HomeShell(key: const ValueKey('home'), api: widget.api)
              : WelcomeScreen(key: const ValueKey('welcome'), api: widget.api, onSignedIn: () => setState(() {})),
        ),
      ),
    );
  }
}
