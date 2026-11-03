# A private X server with DRI3

Xvfb has no DRI3, so a browser's GPU presentation fails on it however good the driver is.
The live desktop's `:0` has DRI3, but it is in use, and starting a second `termux-x11` is not an
option: the Android app refuses a second untagged server, and a tagged one opens a new window.

This runs Termux:X11's real server, from the installed app's own `libXlorie.so`, with no Android
window. [`CmdEntryPoint.java`](CmdEntryPoint.java) comes before the APK on the classpath and
replaces the one class that tells the app about a new server, making its broadcasts do nothing.
The app never learns of this server. A `-tag` keeps its knock port away from the one `:0` uses.

```sh
tests/browsers/private-lorie/private-lorie :73 &
DISPLAY=:73 xdpyinfo | grep DRI3
```

`test-fullscreen.py --x-server lorie` starts and removes one for each run.

**What it does not show:** nothing reaches Android's screen, so the Android side of presentation
is not exercised. The screen is 1280×1024 and has no input from a person.

`private-lorie.dex` is built on a PC from the Java file. It compiles against the Android SDK's
`android.jar`, with the native methods bound at load time by the app's library:

```sh
javac -source 8 -target 8 -cp android.jar -d classes CmdEntryPoint.java
d8 --min-api 26 --lib android.jar --output . classes/com/termux/x11/*.class
mv classes.dex private-lorie.dex
```
