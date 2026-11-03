#!/bin/sh
# Manually installs chrome and chromium extensions via install_crx <id> <name> <dest_dir>
# Assumes dest_dir corresponds to the browser: /opt/google/chrome/extensions or /usr/share/chromium/extensions


# Ensures .crx versioning succeeds the minimum of `google-chrome-stable` and `ungoogled-chromium` for compatibility.
chrome_prodversion() {
    prodversion=""
    for pkg in google-chrome-stable ungoogled-chromium; do
        v="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null)" || continue
        [ -z "$v" ] && continue
        v="${v#*:}"    # strip epoch, if any
        v="${v%%.*}"   # keep leading major version number
        if [ -z "$prodversion" ] || [ "$v" -lt "$prodversion" ]; then
            prodversion="$v"
        fi
    done
    echo "${prodversion:-130}"
}

install_crx() {
    id="$1"
    name="$2"
    dest_dir="$3"
    prodversion="$(chrome_prodversion)"
    url="https://clients2.google.com/service/update2/crx?response=redirect&prodversion=${prodversion}.0&acceptformat=crx2,crx3&x=id%3D${id}%26installsource%3Dondemand%26uc"
    install_crx_from_url "$url" "$id" "$name" "$dest_dir"
}

# Installs a .crx from an arbitrary CRX URL fetch. Fails safely on error allowing installation of other CRXs.
install_crx_from_url() {
    url="$1"
    id="$2"
    name="$3"
    dest_dir="$4"
    tmp_crx="${TMPDIR:-/tmp}/$id.crx"

    echo "[$name] ==> Downloading extension..."
    http_code="$(curl -sL -w '%{http_code}' "$url" -o "$tmp_crx" || echo 000)"
    if [ "$http_code" = "204" ]; then
        echo "[$name] ==> WARNING: update server has no crx for this prodversion (204), skipping" >&2
        rm -f "$tmp_crx"
        return 0
    fi
    if [ "$http_code" != "200" ]; then
        echo "[$name] ==> WARNING: failed to download $url (HTTP $http_code), skipping" >&2
        rm -f "$tmp_crx"
        return 0
    fi

    version="$(unzip -p "$tmp_crx" manifest.json | grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/.*"([^"]+)"$/\1/')"
    if [ -z "$version" ]; then
        rm -f "$tmp_crx"
        echo "[$name] ==> WARNING: failed to read version from downloaded crx, skipping" >&2
        return 0
    fi

    mkdir -p "$dest_dir"
    chmod 755 "$dest_dir"
    cp "$tmp_crx" "$dest_dir/$id.crx"
    chmod 644 "$dest_dir/$id.crx"
    cat > "$dest_dir/$id.json" <<EOF
{
  "external_crx": "$dest_dir/$id.crx",
  "external_version": "$version"
}
EOF
    chmod 644 "$dest_dir/$id.json"
    rm -f "$tmp_crx"

    echo "[$name] ==> Installed successfully to $dest_dir ($version)"
}
