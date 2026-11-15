# Sahil — Flutter Fintech Demo

An **original fictional fintech application** for a Bahrain-focused technical portfolio. It is not affiliated with any bank, does not collect credentials, and never moves real money.

## Features

- BHD-denominated fictional banking dashboard
- Transaction history, keyword search and incoming/outgoing filters
- Simulated transfers with input and balance validation
- Demo deposits, financial insights and balance visibility toggle
- Responsive Flutter Material 3 interface and light/dark mode
- No backend, account credentials, network access, or real transactions

## Running the application

Install the [Flutter SDK](https://docs.flutter.dev/get-started/install), then:

```sh
flutter create . --platforms=android,web
flutter pub get
flutter run -d chrome
flutter analyze
flutter test
```

The app uses the Flutter SDK and Dart. Platform wrapper files are generated with `flutter create .` and are not included in this source repository.

## Safety and limitations

This is strictly a mock app using fake data and in-memory state. Deposits and transfers are simulated and reset on restart. This project is not a banking product and must not be used with real customer data.

## Verification

The source has been published for review, but building on an emulator and confirming UI behaviour still require testing. The GitHub Actions workflow provides automated analysis and tests on push.

## CV description

**Sahil — Flutter Fintech UI Demo:** Created a fictional BHD banking prototype in Flutter/Dart featuring transaction filtering, input-validated simulated transfers, responsive layout, insights, and light/dark themes.
