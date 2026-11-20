import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// Browser download from memory: the CSV never touches a server URL, so no token ever appears in a link.
Future<bool> saveTextFile(String name, String content) async {
  final blob = web.Blob(<JSAny>[content.toJS].toJS, web.BlobPropertyBag(type: 'text/csv;charset=utf-8'));
  final url = web.URL.createObjectURL(blob);
  final link = web.HTMLAnchorElement()
    ..href = url
    ..download = name;
  web.document.body!.append(link);
  link.click();
  link.remove();
  web.URL.revokeObjectURL(url);
  return true;
}
