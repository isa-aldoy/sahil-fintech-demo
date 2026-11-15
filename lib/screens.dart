import 'package:flutter/material.dart';

import 'api.dart';
import 'main.dart';
import 'strings.dart';

String errorText(Object e) => e is ApiException ? (e.code == 'offline' ? tr('offline') : e.message) : tr('offline');

void toast(BuildContext context, String message) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message), behavior: SnackBarBehavior.floating));

class LanguageButton extends StatelessWidget {
  const LanguageButton({super.key});
  @override
  Widget build(BuildContext context) => TextButton(
        onPressed: () => appLocale.value = Locale(isArabic ? 'en' : 'ar'),
        child: Text(isArabic ? 'English' : 'العربية'),
      );
}

// ------------------------------------------------------------------ welcome

class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key, required this.api, required this.onSignedIn});
  final Api api;
  final VoidCallback onSignedIn;
  @override
  State<WelcomeScreen> createState() => _WelcomeState();
}

class _WelcomeState extends State<WelcomeScreen> {
  final name = TextEditingController();
  final email = TextEditingController();
  final password = TextEditingController();
  bool creating = false;
  bool busy = false;
  String? error;

  Future<void> submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (creating) {
        await widget.api.register(name.text.trim(), email.text.trim(), password.text);
      } else {
        await widget.api.login(email.text.trim(), password.text);
      }
      widget.onSignedIn();
    } catch (e) {
      if (mounted) setState(() => error = errorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Align(alignment: AlignmentDirectional.centerEnd, child: LanguageButton()),
                const SizedBox(height: 12),
                const SahilMark(size: 64),
                const SizedBox(height: 20),
                Text(isArabic ? 'ساحل' : 'Sahil',
                    style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w800, letterSpacing: -1)),
                Text(tr('Simple banking, by the shore.'), style: TextStyle(fontSize: 17, color: scheme.onSurfaceVariant)),
                const SizedBox(height: 32),
                if (creating) ...[
                  TextField(controller: name, decoration: InputDecoration(hintText: tr('Full name'))),
                  const SizedBox(height: 12),
                ],
                TextField(
                  key: const Key('email'),
                  controller: email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  decoration: InputDecoration(hintText: tr('Email')),
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('password'),
                  controller: password,
                  obscureText: true,
                  onSubmitted: (_) => submit(),
                  decoration: InputDecoration(
                      hintText: tr('Password'), helperText: creating ? tr('At least 10 characters') : null),
                ),
                AnimatedSize(
                  duration: const Duration(milliseconds: 200),
                  child: error == null
                      ? const SizedBox(height: 20)
                      : Padding(
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          child: Text(error!, style: TextStyle(color: scheme.error)),
                        ),
                ),
                FilledButton(
                  key: const Key('submit'),
                  onPressed: busy ? null : submit,
                  child: busy
                      ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5))
                      : Text(tr(creating ? 'Create account' : 'Sign in')),
                ),
                TextButton(
                  onPressed: () => setState(() => creating = !creating),
                  child: Text(tr(creating ? 'Have an account? Sign in' : 'New here? Create an account')),
                ),
                if (!creating)
                  TextButton(
                    onPressed: () {
                      email.text = 'demo@sahil.example';
                      password.text = 'Sahil-Demo-2026';
                    },
                    child: Text(tr('Use the demo account')),
                  ),
                const SizedBox(height: 16),
                Text(tr('Demo app. Fictional money only.'),
                    textAlign: TextAlign.center, style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Original Sahil mark: a sun over two shoreline waves.
class SahilMark extends StatelessWidget {
  const SahilMark({super.key, this.size = 40});
  final double size;
  @override
  Widget build(BuildContext context) => Align(
        alignment: AlignmentDirectional.centerStart,
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(color: ink, borderRadius: BorderRadius.circular(size * 0.3)),
          child: CustomPaint(painter: _MarkPainter()),
        ),
      );
}

class _MarkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size s) {
    canvas.drawCircle(Offset(s.width * 0.66, s.height * 0.34), s.width * 0.11, Paint()..color = coral);
    final wave = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s.width * 0.085
      ..strokeCap = StrokeCap.round;
    for (final (i, color) in const [Color(0xFF6FD6CF), sand].indexed) {
      final y = s.height * (0.58 + i * 0.17);
      final path = Path()
        ..moveTo(s.width * 0.2, y)
        ..quadraticBezierTo(s.width * 0.35, y - s.height * 0.1, s.width * 0.5, y)
        ..quadraticBezierTo(s.width * 0.65, y + s.height * 0.1, s.width * 0.8, y);
      canvas.drawPath(path, wave..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// --------------------------------------------------------------------- shell

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.api});
  final Api api;
  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int tab = 0;
  int version = 0; // bumped after money moves so every tab reloads

  void changed() => setState(() => version++);

  @override
  Widget build(BuildContext context) {
    final api = widget.api;
    final pages = [
      DashboardTab(key: ValueKey('d$version'), api: api, onChanged: changed, openActivity: () => setState(() => tab = 1)),
      ActivityTab(key: ValueKey('a$version'), api: api),
      AssistantTab(api: api, onChanged: changed),
      CardTab(api: api),
    ];
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: IndexedStack(index: tab, children: pages),
          ),
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: [
          NavigationDestination(icon: const Icon(Icons.home_outlined), selectedIcon: const Icon(Icons.home_rounded), label: tr('Home')),
          NavigationDestination(icon: const Icon(Icons.receipt_long_outlined), label: tr('Activity')),
          NavigationDestination(icon: const Icon(Icons.auto_awesome_outlined), selectedIcon: const Icon(Icons.auto_awesome), label: tr('Assistant')),
          NavigationDestination(icon: const Icon(Icons.credit_card_outlined), label: tr('Card')),
        ],
      ),
    );
  }
}

/// Loads data once and shows a spinner, an error with retry, or the content.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder});
  final Future<T> Function() load;
  final Widget Function(BuildContext, T, VoidCallback reload) builder;
  @override
  State<Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<Loader<T>> {
  late Future<T> future = widget.load();
  void reload() => setState(() => future = widget.load());
  @override
  Widget build(BuildContext context) => FutureBuilder<T>(
        future: future,
        builder: (context, snap) {
          if (snap.hasError) {
            return Center(
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                Padding(padding: const EdgeInsets.all(24), child: Text(errorText(snap.error!), textAlign: TextAlign.center)),
                IconButton(onPressed: reload, icon: const Icon(Icons.refresh)),
              ]),
            );
          }
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return AnimatedSwitcher(
              duration: const Duration(milliseconds: 250), child: widget.builder(context, snap.data as T, reload));
        },
      );
}

class TxTile extends StatelessWidget {
  const TxTile(this.tx, {super.key});
  final Map tx;
  static const icons = {
    'food': Icons.restaurant_rounded, 'groceries': Icons.shopping_basket_rounded, 'bills': Icons.bolt_rounded,
    'fun': Icons.movie_rounded, 'transport': Icons.local_gas_station_rounded, 'shopping': Icons.shopping_bag_rounded,
    'income': Icons.south_west_rounded,
  };
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final incoming = tx['direction'] == 'in';
    final date = DateTime.parse('${tx['created_at']}').toLocal();
    final sub = [MaterialLocalizations.of(context).formatShortDate(date), if ('${tx['note']}'.isNotEmpty) '${tx['note']}'].join(' · ');
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4),
      leading: CircleAvatar(
        radius: 22,
        backgroundColor: (incoming ? scheme.primary : scheme.onSurface).withAlpha(22),
        child: Icon(icons[tx['category']] ?? (incoming ? Icons.south_west_rounded : Icons.north_east_rounded),
            size: 20, color: incoming ? scheme.primary : scheme.onSurface),
      ),
      title: Text('${tx['title']}\u200E', style: const TextStyle(fontWeight: FontWeight.w600)), // LRM keeps "Layla M." intact in Arabic
      subtitle: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: Text(
        '${incoming ? '+' : ''}${bhd(tx['amount_fils'] as num)}',
        textDirection: TextDirection.ltr,
        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: incoming ? scheme.primary : scheme.onSurface),
      ),
    );
  }
}

// ----------------------------------------------------------------- dashboard

class DashboardTab extends StatefulWidget {
  const DashboardTab({super.key, required this.api, required this.onChanged, required this.openActivity});
  final Api api;
  final VoidCallback onChanged;
  final VoidCallback openActivity;
  @override
  State<DashboardTab> createState() => _DashboardState();
}

class _DashboardState extends State<DashboardTab> {
  bool hidden = false;

  Future<(List, List)> load() async {
    final r = await Future.wait([widget.api.accounts(), widget.api.transactions()]);
    return (r[0], r[1]);
  }

  Map account(List accounts, String kind) => accounts.firstWhere((a) => a['kind'] == kind) as Map;

  Future<void> open(Widget sheet) async {
    final done = await showModalBottomSheet<bool>(
        context: context, isScrollControlled: true, showDragHandle: true, useSafeArea: true, builder: (_) => sheet);
    if (done == true) widget.onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final first = '${widget.api.user?['full_name'] ?? ''}'.split(' ').first;
    return Loader<(List, List)>(
      load: load,
      builder: (context, data, reload) {
        final (accounts, txs) = data;
        final current = account(accounts, 'current');
        final savings = account(accounts, 'savings');
        return RefreshIndicator(
          onRefresh: () async => reload(),
          child: ListView(padding: const EdgeInsets.fromLTRB(20, 12, 20, 24), children: [
            Row(children: [
              const SahilMark(size: 36),
              const SizedBox(width: 12),
              Expanded(child: Text('${tr('Hello')}${isArabic ? '،' : ','} $first', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700))),
              IconButton(
                tooltip: tr('Security'),
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ProfileScreen(api: widget.api))),
                icon: const Icon(Icons.shield_outlined),
              ),
            ]),
            const SizedBox(height: 18),
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(28),
                gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [ink, Color(0xFF0F4A4E)]),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Text(tr('Available balance'), style: const TextStyle(color: Colors.white70, fontSize: 14)),
                  const Spacer(),
                  InkWell(
                    onTap: () => setState(() => hidden = !hidden),
                    child: Icon(hidden ? Icons.visibility_off_outlined : Icons.visibility_outlined, color: Colors.white70, size: 20),
                  ),
                ]),
                const SizedBox(height: 8),
                TweenAnimationBuilder<double>(
                  tween: Tween(begin: 0, end: (current['balance_fils'] as num).toDouble()),
                  duration: const Duration(milliseconds: 700),
                  curve: Curves.easeOutCubic,
                  builder: (_, v, __) => Text.rich(
                    TextSpan(children: [
                      TextSpan(text: hidden ? '•••••' : bhd(v.round())),
                      TextSpan(text: '  ${tr('BHD')}', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500, color: Colors.white70)),
                    ]),
                    textDirection: TextDirection.ltr,
                    style: const TextStyle(color: Colors.white, fontSize: 40, fontWeight: FontWeight.w800, letterSpacing: -1),
                  ),
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(color: Colors.white.withAlpha(26), borderRadius: BorderRadius.circular(12)),
                  child: Text('${tr('Savings')}  ${hidden ? '•••' : bhd(savings['balance_fils'] as num)}',
                      style: const TextStyle(color: Colors.white, fontSize: 13)),
                ),
              ]),
            ),
            const SizedBox(height: 18),
            Row(children: [
              _Action(Icons.north_east_rounded, tr('Send'), primary: true, onTap: () => open(SendSheet(api: widget.api, from: '${current['id']}'))),
              const SizedBox(width: 12),
              _Action(Icons.add_rounded, tr('Add money'),
                  onTap: () => open(AmountSheet(title: tr('Add demo money'), action: tr('Add'),
                      run: (amount, key) => widget.api.topUp('${current['id']}', amount, key)))),
              const SizedBox(width: 12),
              _Action(Icons.savings_outlined, tr('Save'),
                  onTap: () => open(AmountSheet(title: tr('Move to savings'), action: tr('Move'),
                      run: (amount, key) => widget.api.transfer('${current['id']}', '${savings['id']}', amount, '', key)))),
            ]),
            const SizedBox(height: 26),
            Row(children: [
              Expanded(child: Text(tr('Recent activity'), style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700))),
              TextButton(onPressed: widget.openActivity, child: Text(tr('See all'))),
            ]),
            if (txs.isEmpty)
              Padding(padding: const EdgeInsets.all(32), child: Center(child: Text(tr('Nothing here yet'), style: TextStyle(color: scheme.onSurfaceVariant))))
            else
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Column(children: [for (final t in txs.take(5)) TxTile(t as Map)]),
                ),
              ),
          ]),
        );
      },
    );
  }
}

class _Action extends StatelessWidget {
  const _Action(this.icon, this.label, {required this.onTap, this.primary = false});
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool primary;
  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final bg = primary ? scheme.secondary : scheme.surfaceContainerHighest;
    final fg = primary ? Colors.white : scheme.onSurface;
    return Expanded(
      child: Material(
        color: bg,
        borderRadius: BorderRadius.circular(20),
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Column(children: [
              Icon(icon, color: fg),
              const SizedBox(height: 6),
              Text(label, style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 13)),
            ]),
          ),
        ),
      ),
    );
  }
}

// -------------------------------------------------------------------- sheets

class _SheetBody extends StatelessWidget {
  const _SheetBody({required this.title, required this.children});
  final String title;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(24, 0, 24, 24 + MediaQuery.of(context).viewInsets.bottom),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
          const SizedBox(height: 18),
          ...children,
        ]),
      );
}

/// One amount, one button. Used for "Add money" and "Move to savings".
class AmountSheet extends StatefulWidget {
  const AmountSheet({super.key, required this.title, required this.action, required this.run});
  final String title;
  final String action;
  final Future<void> Function(String amount, String key) run;
  @override
  State<AmountSheet> createState() => _AmountSheetState();
}

class _AmountSheetState extends State<AmountSheet> {
  final amount = TextEditingController();
  final key = newIdempotencyKey();
  bool busy = false;
  String? error;

  Future<void> go() async {
    setState(() => busy = true);
    try {
      await widget.run(amount.text.trim(), key);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() { error = errorText(e); busy = false; });
    }
  }

  @override
  Widget build(BuildContext context) => _SheetBody(title: widget.title, children: [
        TextField(
          controller: amount,
          autofocus: true,
          textDirection: TextDirection.ltr,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700),
          decoration: InputDecoration(hintText: '0.000', suffixText: tr('BHD'), errorText: error),
        ),
        const SizedBox(height: 18),
        FilledButton(onPressed: busy ? null : go, child: Text(widget.action)),
      ]);
}

/// Send money in two steps: fill in, then review and confirm.
class SendSheet extends StatefulWidget {
  const SendSheet({super.key, required this.api, required this.from});
  final Api api;
  final String from;
  @override
  State<SendSheet> createState() => _SendSheetState();
}

class _SendSheetState extends State<SendSheet> {
  final to = TextEditingController();
  final amount = TextEditingController();
  final note = TextEditingController();
  final key = newIdempotencyKey();
  List recents = [];
  Map<String, dynamic>? recipient;
  Map<String, dynamic>? receipt;
  bool busy = false;
  String? error;

  @override
  void initState() {
    super.initState();
    widget.api.recentRecipients().then((r) { if (mounted) setState(() => recents = r); }).catchError((_) {});
  }

  Future<void> guard(Future<void> Function() work) async {
    setState(() { busy = true; error = null; });
    try {
      await work();
    } catch (e) {
      if (mounted) setState(() => error = errorText(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> review() => guard(() async {
        final r = await widget.api.lookup(to.text.trim());
        if (mounted) setState(() => recipient = r);
      });

  Future<void> send() => guard(() async {
        final r = await widget.api.transfer(widget.from, '${recipient!['handle']}', amount.text.trim(), note.text.trim(), key);
        if (mounted) setState(() => receipt = r);
      });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    if (receipt != null) {
      return _SheetBody(title: tr('Sent'), children: [
        TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: 1),
          duration: const Duration(milliseconds: 450),
          curve: Curves.elasticOut,
          builder: (_, v, child) => Transform.scale(scale: v, child: child),
          child: Icon(Icons.check_circle_rounded, size: 72, color: scheme.primary),
        ),
        const SizedBox(height: 12),
        Text('${receipt!['amount']} ${tr('BHD')} → ${receipt!['to_name']}',
            textAlign: TextAlign.center, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 20),
        FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(tr('Done'))),
      ]);
    }
    if (recipient != null) {
      return _SheetBody(title: tr('Confirm'), children: [
        Card(
          child: ListTile(
            leading: CircleAvatar(child: Text('${recipient!['display_name']}'.characters.first)),
            title: Text('${recipient!['display_name']}\u200E', style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text('@${recipient!['handle']}'),
            trailing: Text('${amount.text.trim()} ${tr('BHD')}', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          ),
        ),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: TextStyle(color: scheme.error))),
        const SizedBox(height: 18),
        FilledButton(key: const Key('confirm-send'), onPressed: busy ? null : send, child: Text(tr('Confirm'))),
        const SizedBox(height: 8),
        TextButton(onPressed: busy ? null : () => setState(() { recipient = null; error = null; }), child: Text(tr('Cancel'))),
      ]);
    }
    return _SheetBody(title: tr('Send money'), children: [
      if (recents.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Wrap(spacing: 8, children: [
            for (final r in recents)
              ActionChip(label: Text('${r['display_name']}'), onPressed: () => setState(() => to.text = '${r['handle']}')),
          ]),
        ),
      TextField(controller: to, decoration: InputDecoration(hintText: tr('To (@name)'))),
      const SizedBox(height: 12),
      TextField(
        controller: amount,
        textDirection: TextDirection.ltr,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(hintText: tr('Amount (BHD)')),
      ),
      const SizedBox(height: 12),
      TextField(controller: note, maxLength: 140, decoration: InputDecoration(hintText: tr('Note (optional)'), counterText: '')),
      if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: TextStyle(color: scheme.error))),
      const SizedBox(height: 18),
      FilledButton(onPressed: busy ? null : review, child: Text(tr('Continue'))),
    ]);
  }
}

// ------------------------------------------------------------------ activity

class ActivityTab extends StatefulWidget {
  const ActivityTab({super.key, required this.api});
  final Api api;
  @override
  State<ActivityTab> createState() => _ActivityState();
}

class _ActivityState extends State<ActivityTab> {
  String search = '';
  String? direction;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
        child: TextField(
          onSubmitted: (v) => setState(() => search = v.trim()),
          decoration: InputDecoration(hintText: tr('Search'), prefixIcon: const Icon(Icons.search)),
        ),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Row(children: [
          for (final (value, label) in [(null, 'All'), ('in', 'Money in'), ('out', 'Money out')])
            Padding(
              padding: const EdgeInsetsDirectional.only(end: 8),
              child: ChoiceChip(label: Text(tr(label)), selected: direction == value, onSelected: (_) => setState(() => direction = value)),
            ),
        ]),
      ),
      Expanded(
        child: Loader<(List, Map<String, dynamic>)>(
          key: ValueKey('$search|$direction'),
          load: () async {
            final r = await Future.wait([widget.api.transactions(search: search, direction: direction), widget.api.insights()]);
            return (r[0] as List, r[1] as Map<String, dynamic>);
          },
          builder: (context, data, _) {
            final (txs, ins) = data;
            final cats = (ins['categories'] as List).take(4).toList();
            final total = (ins['spent_fils'] as num).toDouble();
            return ListView(padding: const EdgeInsets.fromLTRB(20, 12, 20, 24), children: [
              if (search.isEmpty && direction == null && cats.isNotEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(18),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(tr('Spent in 30 days'), style: TextStyle(color: scheme.onSurfaceVariant)),
                      Text('${ins['spent']} ${tr('BHD')}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 10),
                      for (final c in cats)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 5),
                          child: Row(children: [
                            SizedBox(width: 92, child: Text(tr('${c['category']}'))),
                            Expanded(
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(6),
                                child: LinearProgressIndicator(value: total == 0 ? 0 : (c['amount_fils'] as num) / total, minHeight: 8),
                              ),
                            ),
                            SizedBox(width: 74, child: Text('${c['amount']}', textAlign: TextAlign.end)),
                          ]),
                        ),
                    ]),
                  ),
                ),
              const SizedBox(height: 8),
              if (txs.isEmpty) Padding(padding: const EdgeInsets.all(40), child: Center(child: Text(tr('Nothing here yet')))),
              for (final t in txs) TxTile(t as Map),
            ]);
          },
        ),
      ),
    ]);
  }
}

// ----------------------------------------------------------------- assistant

class AssistantTab extends StatefulWidget {
  const AssistantTab({super.key, required this.api, required this.onChanged});
  final Api api;
  final VoidCallback onChanged;
  @override
  State<AssistantTab> createState() => _AssistantState();
}

class _AssistantState extends State<AssistantTab> {
  final input = TextEditingController();
  final scroll = ScrollController();
  final messages = <Map<String, dynamic>>[];
  bool busy = false;

  @override
  void initState() {
    super.initState();
    widget.api.chatHistory().then((h) {
      if (mounted) setState(() => messages.insertAll(0, [for (final m in h) {'role': m['role'], 'content': m['content']}]));
    }).catchError((_) {});
  }

  void toEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (scroll.hasClients) scroll.animateTo(scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      });

  Future<void> ask(String text) async {
    text = text.trim();
    if (text.isEmpty || busy) return;
    input.clear();
    setState(() { messages.add({'role': 'user', 'content': text}); busy = true; });
    toEnd();
    try {
      final r = await widget.api.chat(text);
      messages.add({'role': 'assistant', 'content': r['reply'], 'proposal': r['proposal']});
    } catch (e) {
      messages.add({'role': 'assistant', 'content': errorText(e)});
    }
    if (mounted) setState(() => busy = false);
    toEnd();
  }

  Future<void> decide(Map<String, dynamic> m, bool confirm) async {
    final id = '${(m['proposal'] as Map)['id']}';
    try {
      if (confirm) {
        await widget.api.confirmAction(id);
      } else {
        await widget.api.cancelAction(id);
      }
      setState(() => m['done'] = tr(confirm ? 'Sent' : 'Cancelled'));
      if (confirm) widget.onChanged();
    } catch (e) {
      if (mounted) toast(context, errorText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(children: [
      Expanded(
        child: messages.isEmpty
            ? Center(
                child: Padding(
                  padding: const EdgeInsets.all(28),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.auto_awesome, size: 40, color: scheme.secondary),
                    const SizedBox(height: 14),
                    Text(tr('Ask me about your balance, spending, or to prepare a transfer. Nothing is sent until you confirm.'),
                        textAlign: TextAlign.center, style: TextStyle(color: scheme.onSurfaceVariant, height: 1.4)),
                    const SizedBox(height: 18),
                    Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.center, children: [
                      for (final s in ['What is my balance?', 'How much did I spend?', 'Send 5 to layla'])
                        ActionChip(label: Text(tr(s)), onPressed: () => ask(tr(s))),
                    ]),
                  ]),
                ),
              )
            : ListView.builder(
                controller: scroll,
                padding: const EdgeInsets.all(16),
                itemCount: messages.length,
                itemBuilder: (context, i) {
                  final m = messages[i];
                  final mine = m['role'] == 'user';
                  final proposal = m['proposal'] as Map?;
                  return Align(
                    alignment: mine ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
                    child: Container(
                      constraints: const BoxConstraints(maxWidth: 340),
                      margin: const EdgeInsets.symmetric(vertical: 5),
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: mine ? scheme.primary : scheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${m['content']}', style: TextStyle(color: mine ? scheme.onPrimary : scheme.onSurface, height: 1.35)),
                        if (proposal != null) ...[
                          const Divider(height: 22),
                          Text('${proposal['amount']} ${tr('BHD')} → ${proposal['to_name']}', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                          const SizedBox(height: 10),
                          if (m['done'] != null)
                            Text('${m['done']}', style: TextStyle(color: scheme.primary, fontWeight: FontWeight.w700))
                          else
                            Row(children: [
                              Expanded(child: FilledButton(
                                  style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
                                  onPressed: () => decide(m, true), child: Text(tr('Confirm')))),
                              const SizedBox(width: 8),
                              TextButton(onPressed: () => decide(m, false), child: Text(tr('Cancel'))),
                            ]),
                        ],
                      ]),
                    ),
                  );
                },
              ),
      ),
      if (busy) const LinearProgressIndicator(minHeight: 2),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Row(children: [
          Expanded(child: TextField(controller: input, maxLength: 1000, onSubmitted: ask,
              decoration: InputDecoration(hintText: tr('Ask about your money…'), counterText: ''))),
          const SizedBox(width: 8),
          IconButton.filled(onPressed: () => ask(input.text), icon: const Icon(Icons.arrow_upward_rounded)),
        ]),
      ),
    ]);
  }
}

// ---------------------------------------------------------------------- card

class CardTab extends StatelessWidget {
  const CardTab({super.key, required this.api});
  final Api api;
  @override
  Widget build(BuildContext context) => Loader<Map<String, dynamic>>(
        load: api.card,
        builder: (context, first, _) => _CardView(api: api, card: first),
      );
}

class _CardView extends StatefulWidget {
  const _CardView({required this.api, required this.card});
  final Api api;
  final Map<String, dynamic> card;
  @override
  State<_CardView> createState() => _CardViewState();
}

class _CardViewState extends State<_CardView> {
  late Map<String, dynamic> card = widget.card;

  Future<void> change(String field, bool value) async {
    try {
      final c = await widget.api.updateCard({field: value});
      setState(() => card = c);
    } catch (e) {
      if (mounted) toast(context, errorText(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final frozen = card['frozen'] == true;
    return ListView(padding: const EdgeInsets.all(20), children: [
      AnimatedOpacity(
        duration: const Duration(milliseconds: 300),
        opacity: frozen ? 0.45 : 1,
        child: AspectRatio(
          aspectRatio: 1.586,
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF0F5C5E), ink]),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text(isArabic ? 'ساحل' : 'Sahil', style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
                const Spacer(),
                Text(tr(frozen ? 'Card frozen' : 'Virtual card'), style: const TextStyle(color: Colors.white70, fontSize: 12)),
              ]),
              const Spacer(),
              Text('••••  ••••  ••••  ${card['last4']}', textDirection: TextDirection.ltr,
                  style: const TextStyle(color: Colors.white, fontSize: 21, letterSpacing: 2)),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(child: Text('${card['holder']}'.toUpperCase(), style: const TextStyle(color: Colors.white70, fontSize: 13))),
                Text('${card['expiry']}', style: const TextStyle(color: Colors.white70, fontSize: 13)),
              ]),
            ]),
          ),
        ),
      ),
      const SizedBox(height: 20),
      Card(
        child: Column(children: [
          SwitchListTile(
            secondary: const Icon(Icons.ac_unit_rounded), title: Text(tr('Freeze card')),
            value: frozen, onChanged: (v) => change('frozen', v)),
          SwitchListTile(
            secondary: const Icon(Icons.language_rounded), title: Text(tr('Online payments')),
            value: card['online_payments'] == true, onChanged: (v) => change('online_payments', v)),
        ]),
      ),
    ]);
  }
}

// ------------------------------------------------------------------- profile

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key, required this.api});
  final Api api;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Security'))),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Loader<(List, List)>(
            load: () async {
              final r = await Future.wait([api.sessions(), api.securityActivity()]);
              return (r[0], r[1]);
            },
            builder: (context, data, reload) {
              final (sessions, activity) = data;
              return ListView(padding: const EdgeInsets.all(20), children: [
                Card(
                  child: Column(children: [
                    ListTile(leading: const Icon(Icons.translate_rounded), title: Text(tr('Language')), trailing: const LanguageButton()),
                    SwitchListTile(
                      secondary: const Icon(Icons.dark_mode_outlined), title: Text(tr('Dark mode')),
                      value: appDark.value, onChanged: (v) => appDark.value = v),
                  ]),
                ),
                const SizedBox(height: 20),
                Text(tr('Signed-in devices'), style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Card(
                  child: Column(children: [
                    for (final s in sessions)
                      ListTile(
                        leading: const Icon(Icons.devices_rounded),
                        title: Text('${s['device']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                        subtitle: s['current'] == true ? Text(tr('This device'), style: TextStyle(color: scheme.primary)) : null,
                        trailing: s['current'] == true
                            ? null
                            : TextButton(
                                onPressed: () async {
                                  await api.revokeSession('${s['id']}');
                                  reload();
                                },
                                child: Text(tr('Sign out'))),
                      ),
                  ]),
                ),
                const SizedBox(height: 20),
                Text(tr('Recent security activity'), style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Card(
                  child: Column(children: [
                    for (final a in activity.take(8))
                      ListTile(
                        dense: true,
                        leading: const Icon(Icons.history_rounded, size: 20),
                        title: Text('${a['title']}'),
                        trailing: Text(MaterialLocalizations.of(context).formatShortDate(DateTime.parse('${a['at']}').toLocal()),
                            style: TextStyle(color: scheme.onSurfaceVariant, fontSize: 12)),
                      ),
                  ]),
                ),
                const SizedBox(height: 24),
                FilledButton.tonal(
                  onPressed: () async {
                    Navigator.pop(context);
                    await api.logout();
                  },
                  child: Text(tr('Sign out'))),
                TextButton(
                  onPressed: () async {
                    Navigator.pop(context);
                    await api.logout(everywhere: true);
                  },
                  child: Text(tr('Sign out everywhere'), style: TextStyle(color: scheme.error))),
              ]);
            },
          ),
        ),
      ),
    );
  }
}
