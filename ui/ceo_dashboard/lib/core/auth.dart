// Token extraction + Riverpod provider — Part 8 Stage 2 (Q5).

import 'package:flutter_riverpod/flutter_riverpod.dart';

class AuthConfig {
  final String token;
  final String apiBaseUrl;
  final String wsUrl;

  AuthConfig({
    required this.token,
    required this.apiBaseUrl,
    required this.wsUrl,
  });

  /// Parse token + infer endpoints from the current page Uri.
  /// Token may come from ``?token=...`` query or window storage (fallback).
  factory AuthConfig.fromUri(Uri uri) {
    final token = uri.queryParameters['token'] ?? '';
    final scheme = uri.scheme.isEmpty ? 'http' : uri.scheme;
    final host = uri.host.isEmpty ? '127.0.0.1' : uri.host;
    final port = uri.hasPort ? uri.port : 8000;
    final apiBase = '$scheme://$host:$port';
    final wsScheme = scheme == 'https' ? 'wss' : 'ws';
    final wsUrl = '$wsScheme://$host:$port/ws/dashboard?token=$token';
    return AuthConfig(token: token, apiBaseUrl: apiBase, wsUrl: wsUrl);
  }
}

final authTokenProvider = Provider<AuthConfig>((ref) {
  throw UnimplementedError('Override in main()');
});
