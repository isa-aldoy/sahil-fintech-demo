import 'package:flutter/material.dart';

void main() => runApp(const FintechApp());

class Entry {
  final String title;
  final String category;
  final double amount;
  final DateTime date;
  const Entry(this.title, this.category, this.amount, this.date);
}

class FintechApp extends StatefulWidget {
  const FintechApp({super.key});
  @override
  State<FintechApp> createState() => _FintechAppState();
}

class _FintechAppState extends State<FintechApp> {
  bool darkMode = false;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Sahil · Fictional Banking Demo',
    debugShowCheckedModeBanner: false,
    themeMode: darkMode ? ThemeMode.dark : ThemeMode.light,
    theme: ThemeData(useMaterial3: true, colorSchemeSeed: const Color(0xff116e70)),
    darkTheme: ThemeData(useMaterial3: true, brightness: Brightness.dark, colorSchemeSeed: const Color(0xff50ddba)),
    home: Dashboard(darkMode: darkMode, toggleTheme: () => setState(() => darkMode = !darkMode)),
  );
}

class Dashboard extends StatefulWidget {
  final bool darkMode;
  final VoidCallback toggleTheme;
  const Dashboard({super.key, required this.darkMode, required this.toggleTheme});
  @override
  State<Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<Dashboard> {
  int tab = 0;
  bool hidden = false;
  String query = '';
  String filter = 'All';
  final entries = <Entry>[
    Entry('Monthly allowance', 'Income', 280, DateTime(2026, 11, 15)),
    Entry('Coffee Corner', 'Food', -3.5, DateTime(2026, 11, 14)),
    Entry('City Market', 'Shopping', -12.85, DateTime(2026, 11, 13)),
    Entry('Mobile top-up', 'Utilities', -6, DateTime(2026, 11, 12)),
    Entry('Refund', 'Income', 15.25, DateTime(2026, 11, 11)),
  ];

  double get balance => 420.75 + entries.fold<double>(0, (sum, e) => sum + e.amount);
  double get income => entries.where((e) => e.amount > 0).fold<double>(0, (sum, e) => sum + e.amount);
  double get spending => entries.where((e) => e.amount < 0).fold<double>(0, (sum, e) => sum - e.amount);
  String bhd(double value) => '${value.toStringAsFixed(3)} BHD';

  Future<void> transfer() async {
    final recipient = TextEditingController();
    final amount = TextEditingController();
    final key = GlobalKey<FormState>();
    try {
      final submitted = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Simulate a transfer'),
          content: Form(
            key: key,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('Demo only. No actual money is transferred.'),
                const SizedBox(height: 14),
                TextFormField(
                  controller: recipient,
                  maxLength: 40,
                  decoration: const InputDecoration(labelText: 'Recipient', border: OutlineInputBorder()),
                  validator: (s) => s == null || s.trim().isEmpty ? 'Enter a recipient' : null,
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: amount,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: 'Amount (BHD)', border: OutlineInputBorder()),
                  validator: (s) {
                    final v = double.tryParse(s?.trim() ?? '');
                    if (v == null || !v.isFinite || v <= 0) return 'Enter a positive amount';
                    if (v > balance) return 'Amount exceeds demo balance';
                    return null;
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                if (key.currentState!.validate()) Navigator.pop(ctx, true);
              },
              child: const Text('Simulate'),
            ),
          ],
        ),
      );
      if (submitted == true && mounted) {
        setState(() => entries.insert(0, Entry(recipient.text.trim(), 'Simulated transfer', -double.parse(amount.text.trim()), DateTime.now())));
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Demo transaction saved locally. No money was sent.')));
      }
    } finally {
      // Disposing after a dialog frame prevents stale controllers in the closing animation.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        recipient.dispose();
        amount.dispose();
      });
    }
  }

  void deposit() {
    setState(() => entries.insert(0, Entry('Demo deposit', 'Simulated income', 25, DateTime.now())));
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Added 25.000 BHD of imaginary funds.')));
  }

  Widget entryTile(Entry entry) => Card(
    child: ListTile(
      leading: CircleAvatar(child: Icon(entry.amount >= 0 ? Icons.south_west : Icons.north_east)),
      title: Text(entry.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('${entry.category} · ${entry.date.day}/${entry.date.month}/${entry.date.year}'),
      trailing: Text('${entry.amount < 0 ? '-' : '+'}${bhd(entry.amount.abs())}', style: TextStyle(fontWeight: FontWeight.bold, color: entry.amount >= 0 ? Colors.teal : null)),
    ),
  );

  Widget metric(String name, String value, IconData icon) => Card(
    child: ListTile(leading: Icon(icon), title: Text(name), subtitle: Text(value, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 21))),
  );

  Widget action(String name, IconData icon, VoidCallback onTap) => Expanded(
    child: Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 4),
          child: Column(children: [Icon(icon), const SizedBox(height: 6), Text(name, style: const TextStyle(fontSize: 12))]),
        ),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final visible = entries.where((entry) {
      final matches = '${entry.title} ${entry.category}'.toLowerCase().contains(query.toLowerCase());
      return matches && (filter == 'All' || (filter == 'Money in' ? entry.amount > 0 : entry.amount < 0));
    }).toList();

    return Scaffold(
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), label: 'Activity'),
          NavigationDestination(icon: Icon(Icons.insights_outlined), label: 'Insights'),
          NavigationDestination(icon: Icon(Icons.info_outline), label: 'About'),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 740),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Row(children: [
                  const CircleAvatar(backgroundColor: Color(0xff50ddba), child: Icon(Icons.waves)),
                  const SizedBox(width: 12),
                  const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('SAHIL', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, letterSpacing: 2)),
                    Text('A fictional fintech experience', style: TextStyle(fontSize: 11)),
                  ])),
                  IconButton(tooltip: 'Switch theme', onPressed: widget.toggleTheme, icon: Icon(widget.darkMode ? Icons.light_mode : Icons.dark_mode)),
                ]),
                const SizedBox(height: 24),
                if (tab == 0) ...[
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(color: const Color(0xff142c4b), borderRadius: BorderRadius.circular(23)),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        const Expanded(child: Text('Available demo balance', style: TextStyle(color: Colors.white70))),
                        IconButton(tooltip: 'Show or hide balance', onPressed: () => setState(() => hidden = !hidden), icon: Icon(hidden ? Icons.visibility_off : Icons.visibility, color: Colors.white)),
                      ]),
                      const SizedBox(height: 4),
                      Text(hidden ? '••••••' : bhd(balance), style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 24),
                      const Text('SAHIL / DEMO CARD                              •••• 2046', style: TextStyle(color: Color(0xff50ddba), fontSize: 11)),
                    ]),
                  ),
                  const SizedBox(height: 18),
                  Row(children: [
                    action('Transfer', Icons.send, transfer),
                    action('Add funds', Icons.add, deposit),
                    action('Activity', Icons.history, () => setState(() => tab = 1)),
                  ]),
                  const SizedBox(height: 20),
                  const Text('Recent activity', style: TextStyle(fontSize: 21, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  ...entries.take(4).map(entryTile),
                ] else if (tab == 1) ...[
                  const Text('Transactions', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 14),
                  TextField(onChanged: (value) => setState(() => query = value), decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search transactions', border: OutlineInputBorder())),
                  const SizedBox(height: 12),
                  Wrap(spacing: 8, children: ['All', 'Money in', 'Money out'].map((value) => ChoiceChip(
                    label: Text(value), selected: filter == value, onSelected: (_) => setState(() => filter = value),
                  )).toList()),
                  const SizedBox(height: 12),
                  if (visible.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: Text('No matching transactions.'))),
                  ...visible.map(entryTile),
                ] else if (tab == 2) ...[
                  const Text('Insights', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                  const Text('Based on fictional in-memory transactions only.'),
                  const SizedBox(height: 20),
                  metric('Money received', bhd(income), Icons.trending_up),
                  metric('Money spent', bhd(spending), Icons.trending_down),
                  metric('Demo balance', bhd(balance), Icons.account_balance_wallet),
                ] else ...[
                  const Text('About Sahil', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 18),
                  const Text('A personal Flutter portfolio project demonstrating responsive UI, client-side state, transaction filtering, input validation, and theme switching.'),
                  const SizedBox(height: 18),
                  const Text('No real bank integration, credentials, payments, financial advice or personal data. All sample funds are imaginary.'),
                  const SizedBox(height: 18),
                  const Text('Technology: Flutter · Dart · Material 3'),
                ],
                const SizedBox(height: 32),
                const Center(child: Text('DEMO ONLY · NOT AFFILIATED WITH ANY BANK', textAlign: TextAlign.center, style: TextStyle(fontSize: 10))),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
