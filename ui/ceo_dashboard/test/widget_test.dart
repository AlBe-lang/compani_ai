// Smoke test — Part 8 Stage 2.
// Validates the root MaterialApp builds without throwing.
// Deeper coverage (provider overrides, API stubs) deferred to Stage 3.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:ceo_dashboard/core/app.dart';
import 'package:ceo_dashboard/core/auth.dart';

void main() {
  testWidgets('App renders the shell without throwing', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authTokenProvider.overrideWithValue(
            AuthConfig(
              token: 'test',
              apiBaseUrl: 'http://127.0.0.1:8000',
              wsUrl: 'ws://127.0.0.1:8000/ws/dashboard?token=test',
            ),
          ),
        ],
        child: const CeoDashboardApp(),
      ),
    );
    await tester.pump();
    expect(find.text('CompaniAI CEO Dashboard'), findsOneWidget);
  });
}
