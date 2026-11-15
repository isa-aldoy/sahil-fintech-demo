import 'package:flutter/material.dart';

/// App-wide language and theme switches.
final appLocale = ValueNotifier<Locale>(const Locale('en'));
final appDark = ValueNotifier<bool>(false);

bool get isArabic => appLocale.value.languageCode == 'ar';

const _ar = <String, String>{
  'Simple banking, by the shore.': 'مصرفية بسيطة، على الساحل.',
  'Sign in': 'تسجيل الدخول',
  'Create account': 'إنشاء حساب',
  'Email': 'البريد الإلكتروني',
  'Password': 'كلمة المرور',
  'Full name': 'الاسم الكامل',
  'New here? Create an account': 'جديد هنا؟ أنشئ حساباً',
  'Have an account? Sign in': 'لديك حساب؟ سجّل الدخول',
  'Use the demo account': 'استخدم الحساب التجريبي',
  'Demo app. Fictional money only.': 'تطبيق تجريبي. أموال وهمية فقط.',
  'At least 10 characters': '١٠ أحرف على الأقل',
  'Home': 'الرئيسية',
  'Activity': 'الحركات',
  'Assistant': 'المساعد',
  'Card': 'البطاقة',
  'Hello': 'مرحباً',
  'Available balance': 'الرصيد المتاح',
  'Savings': 'الادخار',
  'Send': 'إرسال',
  'Add money': 'إضافة رصيد',
  'Save': 'ادّخار',
  'Recent activity': 'آخر الحركات',
  'See all': 'عرض الكل',
  'Nothing here yet': 'لا يوجد شيء بعد',
  'Search': 'بحث',
  'All': 'الكل',
  'Money in': 'وارد',
  'Money out': 'صادر',
  'Spent in 30 days': 'المصروف في ٣٠ يوماً',
  'Send money': 'إرسال مبلغ',
  'To (@name)': 'إلى (‎@الاسم)',
  'Amount (BHD)': 'المبلغ (د.ب)',
  'Note (optional)': 'ملاحظة (اختياري)',
  'Continue': 'متابعة',
  'Confirm': 'تأكيد',
  'Cancel': 'إلغاء',
  'Sending to': 'الإرسال إلى',
  'Sent': 'تم الإرسال',
  'Done': 'تم',
  'Add demo money': 'إضافة رصيد تجريبي',
  'Move to savings': 'تحويل إلى الادخار',
  'Add': 'إضافة',
  'Move': 'تحويل',
  'Ask about your money…': 'اسأل عن أموالك…',
  'Ask me about your balance, spending, or to prepare a transfer. Nothing is sent until you confirm.':
      'اسألني عن رصيدك أو مصروفاتك أو لتجهيز تحويل. لن يُرسل شيء قبل تأكيدك.',
  'What is my balance?': 'كم رصيدي؟',
  'How much did I spend?': 'كم صرفت؟',
  'Send 5 to layla': 'حوّل 5 إلى layla',
  'Cancelled': 'تم الإلغاء',
  'Freeze card': 'تجميد البطاقة',
  'Online payments': 'المدفوعات عبر الإنترنت',
  'Card frozen': 'البطاقة مجمّدة',
  'Virtual card': 'بطاقة افتراضية',
  'Security': 'الأمان',
  'Signed-in devices': 'الأجهزة المسجّلة',
  'This device': 'هذا الجهاز',
  'Sign out': 'خروج',
  'Recent security activity': 'آخر نشاطات الأمان',
  'Sign out everywhere': 'تسجيل الخروج من كل الأجهزة',
  'Language': 'اللغة',
  'Dark mode': 'الوضع الداكن',
  'offline': 'تعذّر الاتصال بساحل. تأكد من تشغيل الخادم.',
  'BHD': 'د.ب',
  'You': 'أنت',
};

const _en = <String, String>{'offline': "Can't reach Sahil. Check that the server is running."};

String tr(String key) => isArabic ? (_ar[key] ?? key) : (_en[key] ?? key);

/// 12500 -> "12.500"
String bhd(num fils) {
  final v = fils.abs().toInt();
  final whole = (v ~/ 1000).toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+$)'), (_) => ',');
  return '${fils < 0 ? '-' : ''}$whole.${(v % 1000).toString().padLeft(3, '0')}';
}
