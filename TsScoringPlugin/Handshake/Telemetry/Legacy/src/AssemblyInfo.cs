using System;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;

// Public metadata. Human-facing product name: TScoring. No personal information.
// DLL suffix A = the legacy compatibility path.
// The five public DLLs (Input Device, Bridge B, Telemetry B, Bridge A, Telemetry A) share one release version.
[assembly: AssemblyTitle("TScoring Telemetry A")]
[assembly: AssemblyDescription("TScoring telemetry sender for the legacy compatibility path (DLL suffix A): sends the vehicle and track telemetry to the TScoring application.")]
[assembly: AssemblyProduct("TScoring")]
[assembly: AssemblyCompany("Coruge-to")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Coruge-to")]
[assembly: AssemblyConfiguration("")]
[assembly: AssemblyTrademark("")]
[assembly: AssemblyCulture("")]
[assembly: ComVisible(false)]

// The offline tests (and nothing else) reach the internal core through this.
[assembly: InternalsVisibleTo("TsScoringLegacyTelemetryTests")]

// OD-X11 v2: the build contract of this DLL, recorded inside it (the build script / artifact guard compare it with the compiled-in flag and the sidecar; a mismatch fails the stage).
#if LEGACY_JUMP_EXEC
[assembly: AssemblyMetadata("TScoring.LegacyJumpExec", "true")]
[assembly: AssemblyMetadata("TScoring.BuildRole", "Formal")]
#elif TSCORING_DIAGNOSTIC_JUMP_OFF
[assembly: AssemblyMetadata("TScoring.LegacyJumpExec", "false")]
[assembly: AssemblyMetadata("TScoring.BuildRole", "DiagnosticJumpOff")]
#else
[assembly: AssemblyMetadata("TScoring.LegacyJumpExec", "false")]
[assembly: AssemblyMetadata("TScoring.BuildRole", "Unspecified")]
#endif

[assembly: AssemblyVersion("0.14.0.0")]
[assembly: AssemblyFileVersion("0.14.0.0")]
[assembly: AssemblyInformationalVersion("0.14.0.0")]
