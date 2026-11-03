# Battery

Raw capture paths beginning with `temp/` refer to local files excluded from Git.
See the [privacy notes](../privacy.md).

GNOME Shell and Mission Center both read the battery from UPower. This port runs
UPower on the session's private system bus, with a backend that reports Android's
battery. Shell's panel icon needs no change at all. Mission Center's Battery page
needs a small Magpie fix, which is part of its recipe.

Termux's own `upower` package is close but not enough. It reports the percentage
as Wh, always shows 0 W, and has no voltage, cycle count, health or history.
[`livecd-upower`](../../packages/livecd-upower) replaces that backend, and uses
UPower's ordinary system bus instead of moving it to the session bus.

## How it stays current without polling

On Linux, `upowerd` wakes on kernel uevents and also polls every 30 seconds. On the
tested phone, the uevent socket is denied to apps and to shell alike, and sysfs did
not signal `POLLPRI` for these files. Android's own battery event log does push
changes, but an app can only read its own logs, so shell has to do it. That leaves
three paths:

| When | What happens | Timer |
|---|---|---|
| Shizuku available | A helper started once through `rish` follows `battery_level` and `battery_status`, and tells `upowerd` over loopback | None |
| A client wants live numbers | Mission Center calls `Refresh()` on each of its refreshes, so power, voltage and temperature stay live only while it is open | None |
| Shizuku unavailable | `upowerd` polls, at the same 30 seconds as on Linux, and retries the helper every 5 minutes | 30 s |

The `rish` client is a whole Java VM, 63 MB PSS when measured, so it is stopped as
soon as the helper connects. The helper is `sh`, `logcat` and `nc`, about 11 MB RSS
together, mostly shared. It ends with `upowerd`: the socket closing ends `nc`, which
then ends `logcat`. Any app can reach a loopback port, so the helper must first send
a random token that only went through Shizuku. A stranger cannot stop the poll, and
its lines are never read as data.

Android logs `battery_level` only when the percentage changes, not for voltage or
temperature. Between events those two values are as old as the last read, which is
why Mission Center asks for its own.

## Where the numbers come from

Everything except health comes from a single read of
`/sys/class/power_supply/battery/uevent`, which Termux can read by exact path even
though it cannot list the directory. On the tested phone:

| Value | Source | Note |
|---|---|---|
| Percentage, status, voltage, temperature, design capacity | `uevent` | |
| Current | `batt_current_ua_now`, else `POWER_SUPPLY_CURRENT_NOW` | Samsung's `current_now` is in mA, against the kernel's ABI |
| Cycle count | `POWER_SUPPLY_CYCLE_COUNT`, else `battery_cycle` | |
| Health | `mSavedBatteryAsoc` from `dumpsys battery`, through the helper | Needs Shizuku. Samsung-specific, and `fg_asoc` is denied even to shell |
| Energy in Wh | Charge × 3.85 V | An estimate: Android does not publish a cell's nominal voltage |

Phones that block the sysfs read fall back to `termux-battery-status`, which gives
the percentage, state, voltage, current and temperature, but no capacity, so energy
stays unknown rather than invented.

`POWER_SUPPLY_CHARGE_COUNTER` is not used. It reads 1.67 Ah on this phone at 100%.
`POWER_SUPPLY_CHARGE_FULL` counts as a health figure only when it is below the design
capacity, because this driver repeats the design value without measuring anything.
Without a real figure, health is left blank rather than shown as 100%.

The sign of the current also varies by vendor. The direction comes from the state
instead. A full battery reports a rate of 0, because its small noisy current would
otherwise turn into a time to empty.

## Other programs

Nothing has to be patched for a program to get this backend. There is one daemon
binary and one library on the native side, and the private GNOME tree carries no copy
of either. Each way of reaching UPower ends up here:

| A program that | Reaches `livecd-upower` because |
|---|---|
| Uses D-Bus on the system bus, such as Shell, Mutter, Chromium, Electron and Magpie | The controller's daemon owns that bus name |
| Is patched by Termux to use the session bus, such as `kf6-solid`, `lxqt-powermanagement`, `mate-power-manager` and `xfce4-power-manager` | The activation file starts this daemon on that bus when asked. It costs nothing until then |
| Links `libupower-glib`, or imports `UPowerGlib` | `$PREFIX/lib` holds only this library, which uses the system bus |
| Depends on the `upower` package | The package provides `upower (= 1.91.5)`, or on an on-device build the held `upower` holds these files |

apt is the one route that could bring upstream back. On its own, `Conflicts` and
`Provides` do not stop that: for `apt install upower`, or a dependency newer than the
version provided, apt removes `livecd-upower` and installs upstream.
[`apt-preferences`](../../packages/livecd-upower/apt-preferences) forbids the upstream
package, so those requests resolve to this one or fail instead. No package in Termux
today needs a specific `upower` version.

The Debian guest has its own `upowerd` and library. They exist only inside its proot
filesystem, and native programs never load them.

A program started outside the session has no bus to ask, so it sees no battery rather
than a different one.

## Build and run

The desktop controller starts `upowerd`, so a normal start is all that is needed.
To replace Termux's package on a phone without a release, run this in native Termux
and restart the desktop:

```sh
bash tools/build-packages.sh --install livecd-upower
# Compatibility entry point: bash packages/livecd-upower/build-on-device.sh
```

The helper builds the ordinary Termux recipe and installs its `.deb` with APT.
`livecd-upower` replaces `upower`, so development and release builds use the same
ownership and upgrade rules. An old `upower` hold from the earlier direct-copy
helper is lifted before installation. No new hold is added.

`MC_RISH` selects another `rish` location, as it does for Mission Center. Mission
Center must be started inside the session, for example with
`livecd-native exec -- missioncenter`, or it cannot see the bus.

To go back to Termux's package, remove `livecd-upower` and install `upower` with APT.
The Battery page then returns with the false values described above.

## Verification

Tested on the Note10+ on Android 11, with Shizuku+. Raw results are in
the evidence directory (`temp/docs/evidence/battery`).

```sh
python3 tests/upower/test-backend.py
```

| Check | Result |
|---|---|
| Backend suite: values, states, `Refresh()`, token, poll fallback, helper loss, Termux:API fallback, session bus activation | 33 of 33 passed |
| Plain client on Termux's standard session bus config, real battery | Started this binary, 85% health through the helper, and all of it gone when the session ended |
| apt in simulation, with the recipe's `Provides` and pin against a newer upstream | Plain and versioned dependencies stay on this package, a newer requirement fails, and nothing swaps |
| Real battery through real Shizuku | Health 85%, 14.07 of 16.56 Wh, 1022 cycles, client VM gone |
| Started by the desktop controller in a real session | Panel icon shown, DisplayDevice correct |
| Real Android event through the real helper | Two `battery_level` events, from `dumpsys battery set level` and `reset`, each woke it within about 0.5 s |
| No polling on the real battery | `UpdateTime` did not move for 530 s while no battery event occurred |
| `upowerd` CPU, helper connected | 0 ticks in 60 s in the real session, 0 wakeups in 36 s in the suite |
| `upowerd` CPU, Mission Center open | 12 ticks in 45 s, about 0.27% of a core, and 0 after it closes |
| `upowerd` memory | 6.3 MB RSS, against 124 MB for a held `rish` client |
| Mission Center follows changes to every field | State, percentage, voltage, power, temperature and time estimates, using a fake battery |
| Desktop stop | `upowerd` and the whole helper gone |

## Not yet tested

- **A real discharge.** The phone stayed full on USB, so the charging and discharging
  values come from a fake battery directory. The real current's magnitude has not
  been compared with a charger or known load.
- **Mission Center's weekly chart.** UPower records history and answers `GetHistory`,
  but the chart needs samples from before the page opens and has not been seen.
- **Other phones, and Android 12 or later.** Sysfs access and `mSavedBatteryAsoc` are
  known only for this Samsung. Termux:API was exercised only by hiding sysfs here.
- **The recipe's cross-compile.** Its patch applies, and the same patch was built
  natively, but CI has not built it, so the package's `Provides` and pin have only been
  exercised in apt's simulation.
- **A real Termux power manager.** The session bus route was tested with a plain D-Bus
  client. None of those four packages has been installed and run against it.
