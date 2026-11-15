import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sahil_fintech_demo/main.dart';

void main() {
  testWidgets('shows dashboard and transaction navigation', (tester) async {
    await tester.pumpWidget(const FintechApp());
    expect(find.text('SAHIL'), findsOneWidget);
    expect(find.text('Available demo balance'), findsOneWidget);
    await tester.tap(find.text('Activity').last);
    await tester.pumpAndSettle();
    expect(find.text('Transactions'), findsOneWidget);
  });
}
