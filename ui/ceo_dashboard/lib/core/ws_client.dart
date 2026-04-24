// WebSocket client with 3-second auto-reconnect — Part 8 Stage 2.

import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'auth.dart';

enum WsStatus { connecting, connected, disconnected, unauthorized }

class WsState {
  final WsStatus status;
  final Map<String, dynamic>? lastSnapshot;
  final Map<String, dynamic>? lastMetricsTick;
  final String? lastError;

  const WsState({
    required this.status,
    this.lastSnapshot,
    this.lastMetricsTick,
    this.lastError,
  });

  WsState copyWith({
    WsStatus? status,
    Map<String, dynamic>? lastSnapshot,
    Map<String, dynamic>? lastMetricsTick,
    String? lastError,
  }) =>
      WsState(
        status: status ?? this.status,
        lastSnapshot: lastSnapshot ?? this.lastSnapshot,
        lastMetricsTick: lastMetricsTick ?? this.lastMetricsTick,
        lastError: lastError ?? this.lastError,
      );
}

class DashboardWsNotifier extends StateNotifier<WsState> {
  final AuthConfig auth;
  final _eventController = StreamController<Map<String, dynamic>>.broadcast();
  WebSocketChannel? _channel;
  Timer? _reconnectTimer;
  bool _disposed = false;

  DashboardWsNotifier(this.auth) : super(const WsState(status: WsStatus.connecting)) {
    _connect();
  }

  Stream<Map<String, dynamic>> get events => _eventController.stream;

  void _connect() {
    if (_disposed) return;
    state = state.copyWith(status: WsStatus.connecting);
    try {
      _channel = WebSocketChannel.connect(Uri.parse(auth.wsUrl));
      _channel!.stream.listen(
        _onMessage,
        onError: _onError,
        onDone: _onDone,
      );
    } catch (e) {
      _scheduleReconnect('connect_error: $e');
    }
  }

  void _onMessage(dynamic raw) {
    try {
      final data = json.decode(raw as String) as Map<String, dynamic>;
      final type = data['type'];
      if (type == 'snapshot') {
        state = state.copyWith(
          status: WsStatus.connected,
          lastSnapshot: data,
        );
      } else if (type == 'metrics_tick') {
        state = state.copyWith(lastMetricsTick: data);
      } else if (type == 'event') {
        _eventController.add(data);
      }
    } catch (e) {
      // ignore malformed frames
    }
  }

  void _onError(Object e) {
    _scheduleReconnect('ws_error: $e');
  }

  void _onDone() {
    _scheduleReconnect('ws_closed');
  }

  void _scheduleReconnect(String reason) {
    if (_disposed) return;
    state = state.copyWith(status: WsStatus.disconnected, lastError: reason);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), _connect);
  }

  @override
  void dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    _eventController.close();
    super.dispose();
  }
}

final wsNotifierProvider =
    StateNotifierProvider<DashboardWsNotifier, WsState>((ref) {
  final auth = ref.watch(authTokenProvider);
  return DashboardWsNotifier(auth);
});
