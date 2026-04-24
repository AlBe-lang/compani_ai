// Metrics page — Part 8 Stage 2.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/ws_client.dart';

class MetricsPage extends ConsumerWidget {
  const MetricsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tick = ref.watch(wsNotifierProvider).lastMetricsTick;
    final metrics = tick?['metrics'] as Map<String, dynamic>?;
    if (metrics == null) {
      return const Center(child: Text('메트릭 데이터 수신 대기 중…'));
    }
    final rows = metrics.entries.toList()..sort((a, b) => a.key.compareTo(b.key));
    return ListView.separated(
      itemCount: rows.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, i) {
        return ListTile(
          title: Text(rows[i].key),
          trailing: Text('${rows[i].value}'),
        );
      },
    );
  }
}
