// Overview page — Part 8 Stage 2.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/ws_client.dart';

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final ws = ref.watch(wsNotifierProvider);
    final snapshot = ws.lastSnapshot;
    final metrics = ws.lastMetricsTick?['metrics'] as Map<String, dynamic>?
        ?? (snapshot?['metrics'] as Map<String, dynamic>?);

    return ListView(
      children: [
        Text('현재 Run',
            style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            title: Text(snapshot?['run_id'] as String? ?? '-'),
            subtitle: Text('생성: ${snapshot?['generated_at'] ?? '-'}'),
          ),
        ),
        const SizedBox(height: 24),
        Text('실행 요약', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        _MetricsSummary(metrics: metrics),
      ],
    );
  }
}

class _MetricsSummary extends StatelessWidget {
  final Map<String, dynamic>? metrics;
  const _MetricsSummary({required this.metrics});

  @override
  Widget build(BuildContext context) {
    if (metrics == null) {
      return const Card(child: ListTile(title: Text('메트릭 수집기 없음')));
    }
    return Wrap(
      spacing: 16,
      runSpacing: 16,
      children: [
        _StatCard(label: '전체 태스크', value: '${metrics!['total_tasks'] ?? 0}'),
        _StatCard(label: '성공', value: '${metrics!['success_count'] ?? 0}'),
        _StatCard(label: '실패', value: '${metrics!['fail_count'] ?? 0}'),
        _StatCard(
          label: '평균 소요 (s)',
          value: '${metrics!['avg_duration_sec'] ?? 0}',
        ),
        _StatCard(
          label: '폴백 발생',
          value: '${metrics!['fallback_count'] ?? 0}',
        ),
        _StatCard(
          label: 'Peak 메모리 (GB)',
          value: '${metrics!['memory_peak_gb'] ?? 0}',
        ),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  final String label;
  final String value;
  const _StatCard({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 180,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 8),
              Text(value,
                  style: Theme.of(context).textTheme.headlineSmall),
            ],
          ),
        ),
      ),
    );
  }
}
