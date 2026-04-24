// GoRouter configuration — 6 pages including /settings.
// Part 8 Stage 2.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../pages/agents_page.dart';
import '../pages/home_page.dart';
import '../pages/logs_page.dart';
import '../pages/metrics_page.dart';
import '../pages/projects_page.dart';
import '../pages/settings_page.dart';
import 'shell.dart';

final appRouter = GoRouter(
  initialLocation: '/',
  routes: [
    ShellRoute(
      builder: (context, state, child) => DashboardShell(child: child),
      routes: [
        GoRoute(path: '/', builder: (_, __) => const HomePage()),
        GoRoute(path: '/agents', builder: (_, __) => const AgentsPage()),
        GoRoute(path: '/projects', builder: (_, __) => const ProjectsPage()),
        GoRoute(path: '/logs', builder: (_, __) => const LogsPage()),
        GoRoute(path: '/metrics', builder: (_, __) => const MetricsPage()),
        GoRoute(path: '/settings', builder: (_, __) => const SettingsPage()),
      ],
    ),
  ],
  errorBuilder: (context, state) => Scaffold(
    body: Center(child: Text('Not found: ${state.uri}')),
  ),
);
