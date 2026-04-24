// HTTP client for REST calls — Part 8 Stage 2.

import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'auth.dart';

class DashboardApiClient {
  final AuthConfig auth;
  DashboardApiClient(this.auth);

  Future<Map<String, dynamic>> get(String path) async {
    final uri = Uri.parse('${auth.apiBaseUrl}$path');
    final resp = await http.get(uri, headers: {
      'Authorization': 'Bearer ${auth.token}',
    });
    if (resp.statusCode != 200) {
      throw ApiError(resp.statusCode, resp.body);
    }
    return json.decode(resp.body) as Map<String, dynamic>;
  }

  Future<List<dynamic>> getList(String path) async {
    final uri = Uri.parse('${auth.apiBaseUrl}$path');
    final resp = await http.get(uri, headers: {
      'Authorization': 'Bearer ${auth.token}',
    });
    if (resp.statusCode != 200) {
      throw ApiError(resp.statusCode, resp.body);
    }
    return json.decode(resp.body) as List<dynamic>;
  }

  Future<Map<String, dynamic>> patchConfig(
    String field,
    Object? value, {
    bool confirm = false,
  }) async {
    final uri = Uri.parse('${auth.apiBaseUrl}/api/config');
    final resp = await http.patch(
      uri,
      headers: {
        'Authorization': 'Bearer ${auth.token}',
        'Content-Type': 'application/json',
      },
      body: json.encode({'field': field, 'value': value, 'confirm': confirm}),
    );
    if (resp.statusCode != 200) {
      throw ApiError(resp.statusCode, resp.body);
    }
    return json.decode(resp.body) as Map<String, dynamic>;
  }
}

class ApiError implements Exception {
  final int statusCode;
  final String body;
  ApiError(this.statusCode, this.body);

  @override
  String toString() => 'ApiError($statusCode): $body';
}

final apiClientProvider = Provider<DashboardApiClient>((ref) {
  final auth = ref.watch(authTokenProvider);
  return DashboardApiClient(auth);
});
