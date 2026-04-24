// Agents / DNA page — Part 8 Stage 2.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/ws_client.dart';

class AgentsPage extends ConsumerWidget {
  const AgentsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final snapshot = ref.watch(wsNotifierProvider).lastSnapshot;
    final dna = (snapshot?['dna'] as List<dynamic>?) ?? const [];
    if (dna.isEmpty) {
      return const Center(child: Text('아직 등록된 에이전트 DNA 없음'));
    }
    return ListView.separated(
      itemCount: dna.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, i) {
        final entry = dna[i] as Map<String, dynamic>;
        final genes = (entry['genes'] as Map<String, dynamic>?) ?? const {};
        return Card(
          child: ExpansionTile(
            title: Text(entry['agent_id'] as String? ?? '-'),
            subtitle: Text(
              'role=${entry['role']} · tasks=${entry['total_tasks']} · '
              'success_rate=${entry['success_rate']}',
            ),
            children: [
              _GenesGrid(genes: genes.cast<String, num>()),
              ListTile(
                dense: true,
                title: Text(
                  'meeting_participation=${entry['meeting_participation_count']} · '
                  'review_count=${entry['review_count']}',
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _GenesGrid extends StatelessWidget {
  final Map<String, num> genes;
  const _GenesGrid({required this.genes});

  @override
  Widget build(BuildContext context) {
    final entries = genes.entries.toList()..sort((a, b) => a.key.compareTo(b.key));
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Wrap(
        spacing: 12,
        runSpacing: 8,
        children: [
          for (final e in entries)
            Chip(
              label: Text('${e.key}: ${e.value.toStringAsFixed(2)}'),
            ),
        ],
      ),
    );
  }
}
