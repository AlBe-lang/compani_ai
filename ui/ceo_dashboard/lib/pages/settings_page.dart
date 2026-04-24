// Settings page — runtime config mutation with 3-category badges.
// Part 8 Stage 2 (Q3 D 구현) + Stage 3-2½ (HardwareProfile + LLM Provider).

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

// Stage 3-2½ — highlighted at top of settings; rest of the fields flow below.
const _highlightedFields = {
  'hardware_profile',
  'llm_provider',
  'cto_model',
  'slm_model',
  'mlops_model',
};

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
        final allFields = (config['fields'] as Map<String, dynamic>);
        final highlighted = <MapEntry<String, dynamic>>[];
        final others = <MapEntry<String, dynamic>>[];
        for (final e in allFields.entries) {
          if (_highlightedFields.contains(e.key)) {
            highlighted.add(e);
          } else {
            others.add(e);
          }
        }
        others.sort((a, b) => a.key.compareTo(b.key));
        // Keep highlighted order intact: hardware_profile, llm_provider,
        // cto_model, slm_model, mlops_model.
        highlighted.sort((a, b) => _highlightedFields
            .toList()
            .indexOf(a.key)
            .compareTo(_highlightedFields.toList().indexOf(b.key)));

        final env = envAsync.valueOrNull;
        return ListView(
          children: [
            if (env != null) _EnvironmentBanner(env: env),
            const SizedBox(height: 8),
            _SectionHeader(title: '🖥️ 하드웨어 & LLM Provider'),
            for (final field in highlighted)
              _FieldRow(
                name: field.key,
                info: field.value as Map<String, dynamic>,
                onChanged: (value, {confirm = false}) async {
                  await _applyChange(context, ref, field.key, value,
                      confirm: confirm);
                },
              ),
            const SizedBox(height: 16),
            _SectionHeader(title: '⚙️ 기타 설정'),
            for (final field in others)
              _FieldRow(
                name: field.key,
                info: field.value as Map<String, dynamic>,
                onChanged: (value, {confirm = false}) async {
                  await _applyChange(context, ref, field.key, value,
                      confirm: confirm);
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

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        title,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.bold,
            ),
      ),
    );
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

class _FieldRow extends StatefulWidget {
  final String name;
  final Map<String, dynamic> info;
  final Future<void> Function(Object? value, {bool confirm}) onChanged;

  const _FieldRow({
    required this.name,
    required this.info,
    required this.onChanged,
  });

  @override
  State<_FieldRow> createState() => _FieldRowState();
}

class _FieldRowState extends State<_FieldRow> {
  late TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: '${widget.info['value']}');
  }

  @override
  void didUpdateWidget(covariant _FieldRow old) {
    super.didUpdateWidget(old);
    if (widget.info['value'].toString() != _controller.text) {
      _controller.text = '${widget.info['value']}';
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final category = widget.info['category'] as String? ?? 'restart_required';
    final value = widget.info['value'];
    final type = widget.info['type'] as String? ?? 'str';
    final options = (widget.info['options'] as List<dynamic>?)?.cast<String>();
    final sensitive = widget.info['sensitive'] == true;

    return Card(
      child: ListTile(
        title: Row(
          children: [
            Expanded(child: Text(widget.name)),
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
      return _buildDropdown(context, value, options);
    }
    if (type == 'bool') {
      return Switch(
        value: value == true,
        onChanged: (v) => _triggerChange(context, v),
      );
    }
    // Stage 3-2½: string fields (model names) get inline text editing with
    // an apply button; numeric fields still display-only until validation
    // rules (min/max, step) are finalised.
    if (type == 'str') {
      return Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              decoration: const InputDecoration(
                isDense: true,
                contentPadding:
                    EdgeInsets.symmetric(horizontal: 8, vertical: 8),
              ),
            ),
          ),
          const SizedBox(width: 8),
          TextButton(
            onPressed: () => _triggerChange(context, _controller.text),
            child: const Text('적용'),
          ),
        ],
      );
    }
    return Text('$value', style: const TextStyle(fontFamily: 'monospace'));
  }

  Widget _buildDropdown(
    BuildContext context,
    Object? value,
    List<String> options,
  ) {
    // Stage 3-2½: llm_provider dropdown has a 권장 badge next to "anthropic".
    final showRecommended = widget.name == 'llm_provider';
    return DropdownButton<String>(
      value: value?.toString(),
      items: [
        for (final opt in options)
          DropdownMenuItem(
            value: opt,
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(opt),
                if (showRecommended && opt == 'anthropic')
                  Padding(
                    padding: const EdgeInsets.only(left: 6),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: Colors.teal.shade700,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Text(
                        '권장',
                        style: TextStyle(fontSize: 10, color: Colors.white),
                      ),
                    ),
                  ),
              ],
            ),
          ),
      ],
      onChanged: (v) => _triggerChange(context, v),
    );
  }

  Future<void> _triggerChange(BuildContext context, Object? newValue) async {
    final category = widget.info['category'] as String? ?? '';
    // Stage 3-2½: first-time selection of a non-ollama provider surfaces a
    // short advisory modal so users understand the local→cloud trade-off.
    if (widget.name == 'llm_provider' &&
        newValue is String &&
        newValue != 'ollama') {
      final ok = await _showProviderAdvisory(context, newValue);
      if (ok != true) return;
    }
    if (category == 'destructive') {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('⚠️ 파괴적 변경 확인'),
          content: Text(
            '${widget.name} 을 $newValue 로 변경합니다.\n\n'
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
      await widget.onChanged(newValue, confirm: true);
    } else {
      await widget.onChanged(newValue);
    }
  }

  Future<bool?> _showProviderAdvisory(
      BuildContext context, String provider) async {
    final isAnthropic = provider == 'anthropic';
    return showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('외부 API 사용 — $provider'),
        content: Text(
          isAnthropic
              ? '외부 API 는 API 키(.env 의 ANTHROPIC_API_KEY) 가 필요하고 호출당 비용이 발생합니다. '
                  'Anthropic Claude 는 한국어 멀티에이전트 오케스트레이션에 가장 안정적이라 '
                  '외부 Provider 중 첫 선택으로 권장됩니다.'
              : '외부 API 는 API 키(.env 의 ${provider.toUpperCase()}_API_KEY) 가 필요하고 '
                  '호출당 비용이 발생합니다. 한국어 작업에서는 Anthropic Claude 가 '
                  '상대적으로 안정적이므로 그쪽을 먼저 검토해 보셔도 좋습니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('계속'),
          ),
        ],
      ),
    );
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
