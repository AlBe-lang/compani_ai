// Events log tail — Part 8 Stage 2.
//
// Dashboard receives 5 bridged EventBus event types. We keep a rolling
// buffer of the last 200 entries so users can see recent activity.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/ws_client.dart';

class LogsPage extends ConsumerStatefulWidget {
  const LogsPage({super.key});

  @override
  ConsumerState<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends ConsumerState<LogsPage> {
  final _entries = <Map<String, dynamic>>[];
  static const _maxEntries = 200;

  @override
  void initState() {
    super.initState();
    final notifier = ref.read(wsNotifierProvider.notifier);
    notifier.events.listen((event) {
      if (!mounted) return;
      setState(() {
        _entries.insert(0, event);
        if (_entries.length > _maxEntries) {
          _entries.removeLast();
        }
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_entries.isEmpty) {
      return const Center(child: Text('아직 수신한 이벤트 없음'));
    }
    return ListView.separated(
      itemCount: _entries.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (_, i) {
        final entry = _entries[i];
        final event = entry['event'] as String? ?? '-';
        final payload = entry['payload'];
        return ListTile(
          dense: true,
          title: Text(event, style: const TextStyle(fontFamily: 'monospace')),
          subtitle: Text(
            payload.toString(),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        );
      },
    );
  }
}
