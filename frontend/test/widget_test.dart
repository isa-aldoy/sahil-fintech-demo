import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:sahil_fintech_demo/api.dart';
import 'package:sahil_fintech_demo/main.dart';
import 'package:sahil_fintech_demo/strings.dart';

/// A tiny stand-in for the backend so widget tests need no network.
MockClient fakeBackend() => MockClient((request) async {
      http.Response json(Object body, [int status = 200]) =>
          http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json; charset=utf-8'});
      final path = request.url.path;
      if (path.endsWith('/auth/login')) {
        final body = jsonDecode(request.body) as Map;
        if (body['password'] != 'Sahil-Demo-2026') {
          return json({'error': {'code': 'invalid_credentials', 'message': 'E-mail or password is incorrect.'}}, 401);
        }
        return json({
          'access_token': 'a', 'refresh_token': 'r', 'expires_in': 600,
          'user': {'id': 'u1', 'email': 'demo@sahil.example', 'handle': 'noor', 'full_name': 'Noor Al Khalifa'},
        });
      }
      if (request.headers['Authorization'] != 'Bearer a') return json({'error': {'code': 'not_signed_in', 'message': 'x'}}, 401);
      if (path.endsWith('/accounts')) {
        return json([
          {'id': 'c1', 'kind': 'current', 'name': 'Everyday', 'number': 'BH00', 'balance_fils': 432500, 'balance': '432.500'},
          {'id': 's1', 'kind': 'savings', 'name': 'Savings', 'number': 'BH01', 'balance_fils': 120000, 'balance': '120.000'},
        ]);
      }
      if (path.endsWith('/transactions')) {
        return json([
          {'id': 1, 'transfer_id': 't', 'account_id': 'c1', 'amount_fils': -1800, 'amount': '-1.800', 'direction': 'out',
           'title': 'Coffee Corner', 'category': 'food', 'note': '', 'kind': 'card', 'created_at': '2026-11-14T09:00:00Z'},
        ]);
      }
      if (path.endsWith('/requests')) {
        return json({
          'incoming': [
            {'id': 'q1', 'direction': 'incoming', 'other_name': 'Layla M.', 'other_handle': 'layla', 'amount_fils': 4000,
             'amount': '4.000', 'note': 'Movie tickets', 'status': 'pending', 'created_at': '2026-11-15T09:00:00Z'},
          ],
          'outgoing': [],
        });
      }
      if (path.endsWith('/insights')) {
        return json({'days': 30, 'spent_fils': 1800, 'spent': '1.800', 'received_fils': 0, 'received': '0.000', 'categories': []});
      }
      if (path.endsWith('/card')) {
        return json({'id': 'k', 'last4': '4242', 'expiry': '11/29', 'holder': 'Noor Al Khalifa', 'frozen': false, 'online_payments': true});
      }
      return json([]);
    });

void main() {
  setUp(() => appLocale.value = const Locale('en'));

  test('formats fils as BHD with three decimals', () {
    expect(bhd(12500), '12.500');
    expect(bhd(1234567), '1,234.567');
    expect(bhd(-5), '-0.005');
  });

  test('idempotency keys are unique and well-formed', () {
    final a = newIdempotencyKey(), b = newIdempotencyKey();
    expect(a, isNot(b));
    expect(RegExp(r'^[0-9a-f]{32}$').hasMatch(a), isTrue);
  });

  testWidgets('wrong password shows the server message and stays signed out', (tester) async {
    await tester.pumpWidget(SahilApp(api: Api(client: fakeBackend())));
    await tester.enterText(find.byKey(const Key('email')), 'demo@sahil.example');
    await tester.enterText(find.byKey(const Key('password')), 'wrong');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();
    expect(find.text('E-mail or password is incorrect.'), findsOneWidget);
    expect(find.text('Available balance'), findsNothing);
  });

  testWidgets('signing in shows the dashboard with the balance from the API', (tester) async {
    await tester.binding.setSurfaceSize(const Size(420, 1400)); // phone-shaped, tall enough for the whole home screen
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(SahilApp(api: Api(client: fakeBackend())));
    expect(find.text('Sign in'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('email')), 'demo@sahil.example');
    await tester.enterText(find.byKey(const Key('password')), 'Sahil-Demo-2026');
    await tester.tap(find.byKey(const Key('submit')));
    await tester.pumpAndSettle();
    expect(find.text('Hello, Noor'), findsOneWidget);
    expect(find.textContaining('432.500', findRichText: true), findsOneWidget);
    expect(find.textContaining('Coffee Corner'), findsWidgets);
    expect(find.textContaining('asked you for 4.000'), findsOneWidget);
    expect(find.text('Pay'), findsOneWidget);
  });

  testWidgets('Arabic switches the app to right-to-left', (tester) async {
    await tester.pumpWidget(SahilApp(api: Api(client: fakeBackend())));
    await tester.tap(find.text('العربية'));
    await tester.pumpAndSettle();
    expect(find.text('تسجيل الدخول'), findsOneWidget);
    expect(Directionality.of(tester.element(find.byKey(const Key('submit')))), TextDirection.rtl);
  });
}
