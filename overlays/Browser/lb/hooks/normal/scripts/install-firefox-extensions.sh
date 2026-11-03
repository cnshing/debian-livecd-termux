#!/bin/sh
# Manually fetches and installs Firefox extensions via install_firefox_xpi <id> <name>

install_firefox_xpi() {
    id="$1"
    name="$2"
    dest_dir="/usr/share/mozilla/extensions/{ec8030f7-c20a-464f-9b0e-13a3a9e97384}"
    encoded_id="$(printf '%s' "$id" | sed 's/{/%7B/g; s/}/%7D/g')"
    api_url="https://addons.mozilla.org/api/v5/addons/addon/$encoded_id/"

    echo "[$name] ==> Fetching extension metadata..."
    url="$(curl -fsSL "$api_url" | jq -r '.current_version.file.url // empty')"
    if [ -z "$url" ]; then
        echo "[$name] ==> ERROR: Failed to resolve download URL from $api_url" >&2
        exit 1
    fi

    echo "[$name] ==> Downloading Firefox extension..."
    mkdir -p "$dest_dir"
    if ! curl -fL "$url" -o "$dest_dir/$id.xpi"; then
        echo "[$name] ==> ERROR: Failed to download $url" >&2
        exit 1
    fi
    echo "[$name] ==> Installed successfully to Firefox"
}
