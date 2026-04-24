// Settings page — runtime config mutation with 3-category badges.
// Part 8 Stage 2 (Q3 D 구현).

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_client.dart';

final configFutureProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final client = ref.watch(apiClientProvider);
  return client.get('/api/config');
});

final environmentFutureProvider =
    FutureProvider<Map<String, dynamic>>((ref) async {
  final client = ref.watch(apiClientProvider);
  return client.get('/api/environment');
});

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final configAsync = ref.watch(configFutureProvider);
    final envAsync = ref.watch(environmentFutureProvider);

    return configAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(child: Text('설정 로드 실패: $e')),
      data: (config) {
        final fields = (config['fields'] as Map<String, dynamic>).entries.toList()
          ..sort((a, b) => a.key.compareTo(b.key));
        final env = envAsync.valueOrNull;
        return ListView(
          children: [
            if (env != null) _EnvironmentBanner(env: env),
            const SizedBox(height: 16),
            for (final field in fields)
              _FieldRow(
                name: field.key,
                info: field.value as Map<String, dynamic>,
                onChanged: (value, {confirm = false}) async {
                  await _applyChange(context, ref, field.key, value, confirm: confirm);
                },
              ),
          ],
        );
      },
    );
  }

  Future<void> _applyChange(
    BuildContext context,
    WidgetRef ref,
    String field,
    Object? value, {
    bool confirm = false,
  }) async {
    final client = ref.read(apiClientProvider);
    try {
      final resp = await client.patchConfig(field, value, confirm: confirm);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(resp['message'] as String? ?? 'OK')),
        );
      }
      ref.invalidate(configFutureProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('실패: $e')),
        );
      }
    }
  }
}

class _EnvironmentBanner extends StatelessWidget {
  final Map<String, dynamic> env;
  const _EnvironmentBanner({required this.env});

  @override
  Widget build(BuildContext context) {
    final total = env['total_memory_gb'];
    final canE5 = env['can_use_e5_large'] == true;
    return Card(
      color: canE5 ? Colors.blueGrey.shade800 : Colors.orange.shade900,
      child: ListTile(
        leading: const Icon(Icons.memory),
        title: Text('시스템 메모리: ${total ?? '?'} GB'),
        subtitle: Text(
          canE5
              ? 'E5_BEST 임베딩 가능 (메모리 여유)'
              : 'E5_BEST 비권장 — 현재 메모리로는 swap 위험. MPNET_BALANCED 또는 MINILM_FAST 권장',
        ),
      ),
    );
  }
}

class _FieldRow extends StatelessWidget {
  final String name;
  final Map<String, dynamic> info;
  final Future<void> Function(Object? value, {bool confirm}) onChanged;

  const _FieldRow({
    required this.name,
    required this.info,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    final category = info['category'] as String? ?? 'restart_required';
    final value = info['value'];
    final type = info['type'] as String? ?? 'str';
    final options = (info['options'] as List<dynamic>?)?.cast<String>();
    final sensitive = info['sensitive'] == true;

    return Card(
      child: ListTile(
        title: Row(
          children: [
            Expanded(child: Text(name)),
            _CategoryBadge(category: category),
          ],
        ),
        subtitle: sensitive
            ? Text('(민감) $value')
            : _buildEditor(context, type, value, options),
      ),
    );
  }

  Widget _buildEditor(
    BuildContext context,
    String type,
    Object? value,
    List<String>? options,
  ) {
    if (options != null && options.isNotEmpty) {
      return DropdownButton<String>(
        value: value?.toString(),
        items: [
          for (final opt in options)
            DropdownMenuItem(value: opt, child: Text(opt)),
        ],
        onChanged: (v) => _triggerChange(context, v),
      );
    }
    if (type == 'bool') {
      return Switch(
        value: value == true,
        onChanged: (v) => _triggerChange(context, v),
      );
    }
    // int / float / str — display-only for Stage 2; inline editing is
    // tracked as a Stage 3 refinement once validation rules are finalised.
    return Text('$value', style: const TextStyle(fontFamily: 'monospace'));
  }

  Future<void> _triggerChange(BuildContext context, Object? newValue) async {
    final category = info['category'] as String? ?? '';
    if (category == 'destructive') {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('⚠️ 파괴적 변경 확인'),
          content: Text(
            '$name 을 $newValue 로 변경합니다.\n\n'
            'Qdrant 컬렉션이 재생성되어 기존 임베딩 데이터가 삭제됩니다.\n'
            '계속하시겠습니까?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('재생성 및 적용'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
      await onChanged(newValue, confirm: true);
    } else {
      await onChanged(newValue);
    }
  }
}

class _CategoryBadge extends StatelessWidget {
  final String category;
  const _CategoryBadge({required this.category});

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (category) {
      'hot_reloadable' => ('즉시 적용', Colors.green),
      'restart_required' => ('다음 프로젝트부터', Colors.amber),
      'destructive' => ('⚠️ 데이터 재생성', Colors.red),
      _ => ('-', Colors.grey),
    };
    return Chip(
      label: Text(label, style: const TextStyle(fontSize: 12)),
      backgroundColor: color.withOpacity(0.3),
    );
  }
}
