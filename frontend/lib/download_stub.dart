import 'package:flutter/services.dart';

/// Mobile/desktop fallback: copy the text so it can be pasted anywhere. Returns false (not a download).
Future<bool> saveTextFile(String name, String content) async {
  await Clipboard.setData(ClipboardData(text: content));
  return false;
}
