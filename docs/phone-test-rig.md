# Phone test rig: Termux over ADB and SSH

Use ADB for Android shell commands and screenshots, and SSH for commands inside
Termux's app sandbox. The native desktop does not require PRoot.

## Before using the rig: verify ADB access

Install Android SDK Platform Tools on the PC. Enable USB debugging on the phone,
authorize the PC, and check the connection:

```sh
adb devices -l
adb shell 'echo ADB_OK'
```

For multiple devices, select the intended entry from `adb devices -l`:

```sh
export PHONE_SERIAL='SERIAL_FROM_ADB_DEVICES'
export ANDROID_SERIAL="$PHONE_SERIAL"
adb shell 'echo ADB_OK'
```

`tools/rig.sh` and the host-side resource tests honor `PHONE_SERIAL`, then
`ANDROID_SERIAL`. With neither set, ADB selects the single connected device and
reports an error if the selection is ambiguous. No phone identifier is bundled.

For Android 11+ Wireless debugging, put the PC and phone on the same network.
Open **Settings → Developer options → Wireless debugging → Pair device with
pairing code**, then substitute the endpoints displayed by the phone:

```sh
adb pair PHONE_IP:PAIRING_PORT
adb connect PHONE_IP:DEBUGGING_PORT
adb devices -l
```

Enter the pairing code interactively. The debugging port on the main Wireless
debugging screen differs from the pairing port. Set the serial exports to the
connected entry and repeat the shell check. This flow needs no initial USB
connection. See [Android's ADB instructions](https://developer.android.com/tools/adb#connect-to-a-device-over-wi-fi).

## Configure SSH

In native Termux, install OpenSSH, authorize the PC's public key using your
preferred transfer method, and start the server:

```sh
pkg install openssh
sshd
```

Forward the SSH port from the PC:

```sh
adb forward tcp:8022 tcp:8022
```

Add an alias to the PC's `~/.ssh/config`, using the identity file for your key:

```sshconfig
Host termux
    HostName 127.0.0.1
    Port 8022
    HostKeyAlias termux
    IdentityFile ~/.ssh/termux_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
```

Verify access with `ssh termux 'echo SSH_OK'`. `TERMUX_SSH_HOST` overrides the
`termux` alias in the rig helper and host-side tests. Recreate the port forward
after reconnecting ADB, and restart `sshd` in Termux if it has stopped.

## How it connects

```text
PC → ADB → Android shell and screenshots
        └→ forwarded port 8022 → Termux sshd → native desktop commands
```

Android's ADB shell cannot enter Termux's private app directory directly; SSH
runs commands under the Termux app identity. `127.0.0.1` is the loopback endpoint
for the tunnel, and port 8022 is Termux OpenSSH's standard port.

## Daily use

Run the helper from the repository checkout on the PC:

```sh
bash tools/rig.sh setup
bash tools/rig.sh start
bash tools/rig.sh status
bash tools/rig.sh validate
bash tools/rig.sh screenshot  # prints a new temporary PNG path
bash tools/rig.sh stop
```

The helper recreates the ADB forward before connecting. Other useful commands:

```sh
ssh termux '<command>'
ssh termux 'python -' < script.py
ssh termux 'cat /path/to/file' > file
adb exec-out screencap -p > screenshot.png
```

Keep connection endpoints, pairing codes, keys and device captures out of shared
reports. Store local diagnostic output under the Git-ignored `temp/` directory.
