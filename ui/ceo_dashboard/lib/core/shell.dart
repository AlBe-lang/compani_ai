// Dashboard shell — side navigation + top status bar.
// Part 8 Stage 2. Responsive: rail under 768px, drawer above.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'ws_client.dart';

class DashboardShell extends ConsumerWidget {
  final Widget child;
  const DashboardShell({super.key, required this.child});

  static const _items = [
    ('/', Icons.dashboard, '개요'),
    ('/agents', Icons.groups, '에이전트'),
    ('/projects', Icons.folder, '프로젝트'),
    ('/logs', Icons.article, '로그'),
    ('/metrics', Icons.show_chart, '메트릭'),
    ('/settings', Icons.settings, '설정'),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ws = ref.watch(wsNotifierProvider);
    final currentPath = GoRouterState.of(context).uri.path;
    final isWide = MediaQuery.of(context).size.width >= 768;

    return Scaffold(
      appBar: AppBar(
        title: const Text('CompaniAI CEO Dashboard'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: _ConnectionBadge(status: ws.status),
          ),
        ],
      ),
      body: Row(
        children: [
          if (isWide)
            NavigationRail(
              extended: MediaQuery.of(context).size.width > 1100,
              selectedIndex: _indexOf(currentPath),
              onDestinationSelected: (i) => context.go(_items[i].$1),
              labelType: MediaQuery.of(context).size.width > 1100
                  ? NavigationRailLabelType.none
                  : NavigationRailLabelType.all,
              destinations: [
                for (final item in _items)
                  NavigationRailDestination(
                    icon: Icon(item.$2),
                    label: Text(item.$3),
                  ),
              ],
            ),
          Expanded(child: Padding(padding: const EdgeInsets.all(16), child: child)),
        ],
      ),
      bottomNavigationBar: isWide
          ? null
          : NavigationBar(
              selectedIndex: _indexOf(currentPath),
              onDestinationSelected: (i) => context.go(_items[i].$1),
              destinations: [
                for (final item in _items)
                  NavigationDestination(
                    icon: Icon(item.$2),
                    label: item.$3,
                  ),
              ],
            ),
    );
  }

  static int _indexOf(String path) {
    for (var i = 0; i < _items.length; i++) {
      if (_items[i].$1 == path) return i;
    }
    return 0;
  }
}

class _ConnectionBadge extends StatelessWidget {
  final WsStatus status;
  const _ConnectionBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      WsStatus.connecting => ('연결 중…', Colors.amber),
      WsStatus.connected => ('연결됨', Colors.green),
      WsStatus.disconnected => ('끊김 (3초 후 재연결)', Colors.red),
      WsStatus.unauthorized => ('토큰 오류', Colors.red.shade900),
    };
    return Row(
      children: [
        Icon(Icons.circle, size: 10, color: color),
        const SizedBox(width: 6),
        Text(label),
      ],
    );
  }
}
