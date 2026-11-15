import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

/// Where the Sahil API lives. Override with --dart-define=API_BASE_URL=...
const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://localhost:8000');

class ApiException implements Exception {
  ApiException(this.status, this.code, this.message);
  final int status;
  final String code;
  final String message;
  @override
  String toString() => message;
}

/// A fresh random key per user action, reused on retries so a transfer can never run twice.
String newIdempotencyKey() {
  final r = Random.secure();
  return List.generate(32, (_) => r.nextInt(16).toRadixString(16)).join();
}

/// Talks to the backend. Tokens are kept in memory only: nothing sensitive is written
/// to disk or browser storage, so closing the app signs you out.
class Api {
  Api({http.Client? client, this.baseUrl = apiBaseUrl}) : _client = client ?? http.Client();

  final http.Client _client;
  final String baseUrl;
  String? _access;
  String? _refresh;
  Future<bool>? _refreshing;
  Map<String, dynamic>? user;
  void Function()? onSignedOut;

  bool get signedIn => _access != null;

  Future<dynamic> _send(String method, String path,
      {Object? body, String? key, bool auth = true, bool retry = true}) async {
    final req = http.Request(method, Uri.parse('$baseUrl$path'));
    req.headers['Content-Type'] = 'application/json';
    if (auth && _access != null) req.headers['Authorization'] = 'Bearer $_access';
    if (key != null) req.headers['Idempotency-Key'] = key;
    if (body != null) req.body = jsonEncode(body);
    final http.Response res;
    try {
      res = await http.Response.fromStream(await _client.send(req).timeout(const Duration(seconds: 25)));
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException(0, 'offline', 'offline');
    }
    if (res.statusCode == 401 && auth && retry && _refresh != null) {
      if (await _refreshOnce()) {
        return _send(method, path, body: body, key: key, retry: false);
      }
      _clear();
      onSignedOut?.call();
    }
    if (res.statusCode >= 400) {
      var code = 'error';
      var message = 'error';
      try {
        final err = (jsonDecode(utf8.decode(res.bodyBytes)) as Map)['error'] as Map;
        code = '${err['code']}';
        message = '${err['message']}';
      } catch (_) {}
      throw ApiException(res.statusCode, code, message);
    }
    if (res.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(res.bodyBytes));
  }

  /// Refresh tokens are single-use, so concurrent 401s must share one refresh call.
  Future<bool> _refreshOnce() => _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);

  Future<bool> _doRefresh() async {
    try {
      final t = await _send('POST', '/api/v1/auth/refresh', body: {'refresh_token': _refresh}, auth: false);
      _access = t['access_token'] as String;
      _refresh = t['refresh_token'] as String;
      return true;
    } catch (_) {
      return false;
    }
  }

  void _clear() {
    _access = null;
    _refresh = null;
    user = null;
  }

  void _store(dynamic t) {
    _access = t['access_token'] as String;
    _refresh = t['refresh_token'] as String;
    user = Map<String, dynamic>.from(t['user'] as Map);
  }

  Future<void> login(String email, String password) async =>
      _store(await _send('POST', '/api/v1/auth/login', body: {'email': email, 'password': password}, auth: false));

  Future<void> register(String name, String email, String password) async => _store(await _send(
      'POST', '/api/v1/auth/register',
      body: {'full_name': name, 'email': email, 'password': password}, auth: false));

  Future<void> logout({bool everywhere = false}) async {
    try {
      await _send('POST', everywhere ? '/api/v1/auth/logout-all' : '/api/v1/auth/logout');
    } catch (_) {}
    _clear();
    onSignedOut?.call();
  }

  Future<List<dynamic>> accounts() async => await _send('GET', '/api/v1/accounts') as List;

  Future<List<dynamic>> transactions({String search = '', String? direction}) async {
    final q = <String, String>{
      'limit': '50',
      if (search.isNotEmpty) 'search': search,
      if (direction != null) 'direction': direction,
    };
    return await _send('GET', '/api/v1/transactions?${Uri(queryParameters: q).query}') as List;
  }

  Future<Map<String, dynamic>> insights() async =>
      Map<String, dynamic>.from(await _send('GET', '/api/v1/insights') as Map);

  Future<List<dynamic>> recentRecipients() async => await _send('GET', '/api/v1/recipients/recent') as List;

  Future<Map<String, dynamic>> lookup(String q) async => Map<String, dynamic>.from(
      await _send('GET', '/api/v1/recipients/lookup?${Uri(queryParameters: {'q': q}).query}') as Map);

  Future<Map<String, dynamic>> transfer(String from, String to, String amount, String note, String key) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/v1/transfers',
          key: key, body: {'from_account_id': from, 'to': to, 'amount': amount, 'note': note}) as Map);

  Future<void> topUp(String account, String amount, String key) async =>
      _send('POST', '/api/v1/accounts/$account/top-up', key: key, body: {'amount': amount});

  Future<Map<String, dynamic>> card() async => Map<String, dynamic>.from(await _send('GET', '/api/v1/card') as Map);

  Future<Map<String, dynamic>> updateCard(Map<String, bool> changes) async =>
      Map<String, dynamic>.from(await _send('PATCH', '/api/v1/card', body: changes) as Map);

  Future<List<dynamic>> sessions() async => await _send('GET', '/api/v1/auth/sessions') as List;
  Future<void> revokeSession(String id) async => _send('DELETE', '/api/v1/auth/sessions/$id');
  Future<List<dynamic>> securityActivity() async => await _send('GET', '/api/v1/security/activity') as List;

  Future<Map<String, dynamic>> chat(String message) async =>
      Map<String, dynamic>.from(await _send('POST', '/api/chat', body: {'message': message}) as Map);
  Future<List<dynamic>> chatHistory() async => await _send('GET', '/api/chat/history') as List;
  Future<void> confirmAction(String id) async => _send('POST', '/api/v1/assistant/actions/$id/confirm');
  Future<void> cancelAction(String id) async => _send('POST', '/api/v1/assistant/actions/$id/cancel');
}
