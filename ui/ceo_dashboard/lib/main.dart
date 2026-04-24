// Part 8 Stage 2 — CEO Dashboard entry point.
//
// Extracts the API token from the URL query (?token=...), seeds the Riverpod
// scope with it, and hands off to GoRouter. The token remains in the URL so
// users can bookmark the page; on a fresh reload the router picks it up again.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/app.dart';
import 'core/auth.dart';

void main() {
  final token = AuthConfig.fromUri(Uri.base);
  runApp(
    ProviderScope(
      overrides: [
        authTokenProvider.overrideWithValue(token),
      ],
      child: const CeoDashboardApp(),
    ),
  );
}
