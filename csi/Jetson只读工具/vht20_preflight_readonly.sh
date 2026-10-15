#!/bin/sh
# Read-only inventory for the existing wlan0. No sudo, writes, scan or reconnect.
# Run on Jetson only after it has booted; keep output private.
set -u

date -Is
uname -r
readlink -f /sys/class/net/wlan0/device/driver
module_path=$(readlink -f /sys/class/net/wlan0/device/driver/module 2>/dev/null || true)
module=$(basename "$module_path")
printf 'module=%s\n' "$module"
if command -v ethtool >/dev/null 2>&1; then
    ethtool -i wlan0
fi
if command -v modinfo >/dev/null 2>&1 && [ -n "$module_path" ]; then
    modinfo -F version "$module"
    modinfo -F filename "$module"
    modinfo -p "$module" | grep -Ei '(^|_)(bw|bandwidth|vht)|tx_bw' || true
fi

for name in rtw_bw_mode rtw_tx_bw_mode rtw_vht_enable; do
    file="/sys/module/$module/parameters/$name"
    if [ -e "$file" ]; then
        ls -l "$file"
        cat "$file"
    fi
done

# Only established read-only status nodes, never sec_cam/key material.
# Proc directory name and kernel module name can be different.
for base in /proc/net/rtl8821cu /proc/net/8821cu; do
    if [ -d "$base" ]; then
        ls -ld "$base" "$base/wlan0" 2>/dev/null || true
        for file in "$base/ver_info" "$base/drv_cfg" "$base/wlan0/tx_bw_mode" "$base/wlan0/rf_info" "$base/wlan0/ap_info"; do
            if [ -e "$file" ]; then
                printf 'read-only node: %s\n' "$file"
                ls -l "$file"
                cat "$file"
            fi
        done
    fi
done

iw dev wlan0 link
if command -v iwconfig >/dev/null 2>&1; then
    iwconfig wlan0
fi
ip -br addr
ip -4 route show default
ip rule show
if [ -n "${SSH_CONNECTION:-}" ]; then
    client_ip=${SSH_CONNECTION%% *}
    ip route get "$client_ip"
fi

printf 'Read-only preflight complete. No bandwidth or connection changes made.\n'
