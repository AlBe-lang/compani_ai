// Projects / WorkItem tree — Part 8 Stage 2.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/ws_client.dart';

class ProjectsPage extends ConsumerWidget {
  const ProjectsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(wsNotifierProvider).lastSnapshot;
    final items = (snapshot?['workitems'] as List<dynamic>?) ?? const [];
    if (items.isEmpty) {
      return const Center(child: Text('진행 중인 WorkItem 없음'));
    }
    return ListView.separated(
      itemCount: items.length,
      separatorBuilder: (_, __) => const Divider(),
      itemBuilder: (_, i) {
        final item = items[i] as Map<String, dynamic>;
        final status = item['status'] as String? ?? '-';
        return ListTile(
          leading: _StatusIcon(status: status),
          title: Text(item['task_id'] as String? ?? item['id'] as String),
          subtitle: Text(
            'agent=${item['agent_id']} · status=$status · '
            'rework=${item['rework_count']}',
          ),
          trailing: Text(item['updated_at'] as String? ?? ''),
        );
      },
    );
  }
}

class _StatusIcon extends StatelessWidget {
  final String status;
  const _StatusIcon({required this.status});

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (status) {
      'DONE' => (Icons.check_circle, Colors.green),
      'IN_PROGRESS' => (Icons.autorenew, Colors.blue),
      'WAITING' => (Icons.hourglass_empty, Colors.orange),
      'BLOCKED' => (Icons.block, Colors.red),
      'FAILED' => (Icons.error, Colors.red),
      _ => (Icons.circle_outlined, Colors.grey),
    };
    return Icon(icon, color: color);
  }
}
