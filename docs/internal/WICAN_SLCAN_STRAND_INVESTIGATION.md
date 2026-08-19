# WiCAN Bench SLCAN strand — open investigation (August 2026)

Pointer document, so a session that starts in **this** repo finds the work. The full plan,
evidence and code anchors live in the firmware repo:

> `C:\Users\dufre\Projets\nc-flash-wican-fw\docs\internals\bench-slcan-strand-2026-08.md`
> and its evergreen companion `docs/internals/returning-to-datalogger.md`

**Read the plan before doing anything.** Do not re-derive the analysis — it is already written up.

## The one-paragraph version

A WiCAN was found stuck in Bench SLCAN mode with datalogging dead (firmware issue #92). This app
is the only thing that ever writes `protocol: slcan` to a device: `connect_ecu()` probes the
firmware's always-on coexistence port 35001 with a **1500 ms** timeout, and on **any** probe
failure — including a brief network hiccup — falls back to the legacy path, which persists
`slcan` and restores the original only on a clean disconnect or app exit. A session killed in
between strands the device.

**Status: hypothesis, not proven.** The fallback is real and fired here once — `~/.nc-flash/nc-flash.log`,
2026-07-12 12:57:20, `WiCAN dedicated port answered rev=None (< NCFRv6); legacy reboot path` — but
no log covers the 2026-08-11 incident, so the cause of #92 is unattributed.

## Suspected defects in this repo

1. `_try_open_coexist_port()` — ANY probe failure silently downgrades a coexist-capable device to
   the mode-switching path. A hiccup and a genuinely old firmware are treated identically.
2. `_restore_wican_protocol()` and `WiCANConfigurator.slcan_session()` — the breadcrumb delete sits
   in a `finally`, so a **failed** restore destroys the only record of the original mode.
3. No start-up sweep: `read_recovery()` is consulted only when a new session connects, so a device
   stranded by a crash stays stranded if the app is never pointed at it again.
4. The breadcrumb lives in the OS temp directory keyed by IP (`_host_keyed_temp_path()`), so a
   cleanup or a DHCP address change orphans it.

## Next step — Stage 1, no hardware needed

Three tests, each asserting the **desired** behaviour so they are red today and green after a fix.
If all three pass unchanged, the hypothesis is wrong and the investigation stops.

1. Probe raises or times out → it must **not** silently switch the device's mode.
2. `restore()` raises → the breadcrumb file must **still exist**.
3. Breadcrumb present at start-up with no connect → recovery must run.

Run them with `venv-windows\Scripts\python.exe -m pytest` (the PATH python has no PySide6).

## Do not

- Do not "fix" anything before the three tests exist and are seen red — that is the whole point of
  the exercise, per the request that a fix be confirmed by replaying the failure.
- Do not run the bench reproduction (Stage 2 in the plan) casually: it deliberately strands the
  test device, and its teardown must restore the mode.
