// Root MaterialApp.router — Part 8 Stage 2.

import 'package:flutter/material.dart';

import 'router.dart';

class CeoDashboardApp extends StatelessWidget {
  const CeoDashboardApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'CompaniAI CEO Dashboard',
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF0f172a),
          brightness: Brightness.dark,
        ),
      ),
      routerConfig: appRouter,
    );
  }
}
